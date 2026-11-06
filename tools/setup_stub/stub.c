/* NEON-Torrent-Setup.exe: a small native launcher that carries the MSI and the NEON icon.
 *
 * Windows shows every .msi with the generic Windows Installer icon, so the setup users double-click is this exe.
 * tools/build_msi.py appends the MSI to it, followed by a 16-byte trailer: the MSI size (uint64, little endian)
 * and the magic "NEONMSI1". At start the launcher copies the MSI into a new folder under %TEMP%, runs
 * %SystemRoot%\System32\msiexec.exe /i on it (the full installer UI; msiexec asks for UAC itself), waits, and
 * deletes the copy. It runs as the user (asInvoker), so "Launch NEON Torrent" at the end never starts the app
 * elevated. Built with Zig (zig build-exe), no C runtime needed beyond kernel32 and user32. */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdint.h>
#include <string.h>

static const char MAGIC[8] = {'N', 'E', 'O', 'N', 'M', 'S', 'I', '1'};

static int fail(const wchar_t *text) {
    MessageBoxW(NULL, text, L"NEON Torrent Setup", MB_OK | MB_ICONERROR);
    return 1;
}

static BOOL read_at(HANDLE f, int64_t offset, void *buffer, DWORD length) {
    LARGE_INTEGER pos;
    DWORD got = 0;
    pos.QuadPart = offset;
    return SetFilePointerEx(f, pos, NULL, FILE_BEGIN) && ReadFile(f, buffer, length, &got, NULL) && got == length;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command_line, int show) {
    (void)instance; (void)previous; (void)command_line; (void)show;
    /* a setup often runs from Downloads: never load a DLL planted next to it */
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32);

    wchar_t self[32768];
    DWORD n = GetModuleFileNameW(NULL, self, 32768);
    if (n == 0 || n >= 32768) return fail(L"Setup cannot find its own file.");
    HANDLE f = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return fail(L"Setup cannot read its own file.");
    LARGE_INTEGER size;
    uint64_t payload = 0;
    char magic[8];
    if (!GetFileSizeEx(f, &size) || size.QuadPart < 16 || !read_at(f, size.QuadPart - 16, &payload, 8)
            || !read_at(f, size.QuadPart - 8, magic, 8) || memcmp(magic, MAGIC, 8) != 0
            || payload == 0 || payload > (uint64_t)(size.QuadPart - 16)) {
        CloseHandle(f);
        return fail(L"This setup file is damaged. Download it again.");
    }

    /* a fresh folder of our own under %TEMP%: CreateDirectory fails if it already exists, so nothing planted there
       beforehand is ever run */
    wchar_t temp[MAX_PATH + 1], dir[MAX_PATH + 64], msi[MAX_PATH + 96];
    DWORD t = GetTempPathW(MAX_PATH + 1, temp);
    if (t == 0 || t > MAX_PATH) { CloseHandle(f); return fail(L"Setup cannot find the TEMP folder."); }
    int made = 0;
    for (int attempt = 0; attempt < 20 && !made; attempt++) {
        wsprintfW(dir, L"%sNEON-Torrent-Setup-%lu-%lu", temp, GetCurrentProcessId(), GetTickCount() + attempt);
        made = CreateDirectoryW(dir, NULL);
    }
    if (!made) { CloseHandle(f); return fail(L"Setup cannot create a folder in TEMP."); }
    wsprintfW(msi, L"%s\\NEON-Torrent-Setup.msi", dir);

    HANDLE out = CreateFileW(msi, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    BOOL ok = out != INVALID_HANDLE_VALUE;
    LARGE_INTEGER start;
    start.QuadPart = size.QuadPart - 16 - (int64_t)payload;
    ok = ok && SetFilePointerEx(f, start, NULL, FILE_BEGIN);
    static char buffer[1 << 20];
    uint64_t left = payload;
    while (ok && left > 0) {
        DWORD want = left > sizeof(buffer) ? (DWORD)sizeof(buffer) : (DWORD)left, got = 0, wrote = 0;
        ok = ReadFile(f, buffer, want, &got, NULL) && got == want && WriteFile(out, buffer, got, &wrote, NULL)
             && wrote == got;
        left -= got;
    }
    if (out != INVALID_HANDLE_VALUE) CloseHandle(out);
    CloseHandle(f);
    if (!ok) {
        DeleteFileW(msi);
        RemoveDirectoryW(dir);
        return fail(L"Setup cannot unpack the installer. Is the TEMP drive full?");
    }

    /* the full path of msiexec, never a search: msiexec shows the NEON installer pages and asks for UAC itself */
    wchar_t system[MAX_PATH], exe[MAX_PATH + 16], cmd[MAX_PATH * 2 + 128];
    UINT s = GetSystemDirectoryW(system, MAX_PATH);
    if (s == 0 || s >= MAX_PATH) { DeleteFileW(msi); RemoveDirectoryW(dir); return fail(L"Windows folder not found."); }
    wsprintfW(exe, L"%s\\msiexec.exe", system);
    wsprintfW(cmd, L"\"%s\" /i \"%s\"", exe, msi);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    DWORD code = 1;
    if (CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, system, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, INFINITE);
        GetExitCodeProcess(pi.hProcess, &code);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    } else {
        fail(L"Setup cannot start Windows Installer (msiexec.exe).");
    }
    DeleteFileW(msi);
    RemoveDirectoryW(dir);
    return (int)code;
}
