# Runs inside Windows Sandbox (tools\make_msix.py --sandbox): signs the package with a throwaway certificate,
# installs it, launches it and reports to C:\results. Everything here disappears when the sandbox closes.
$ErrorActionPreference = "Stop"
$log = "C:\results\sandbox.log"
function Log([string]$m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }

try {
    Log "sandbox up"
    $work = Join-Path $env:TEMP "neon"
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Copy-Item C:\msix\NeonTorrent.msix $work
    $msix = Join-Path $work "NeonTorrent.msix"

    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=NEON Torrent Test" -CertStoreLocation Cert:\CurrentUser\My
    Export-Certificate -Cert $cert -FilePath (Join-Path $work "test.cer") | Out-Null
    Import-Certificate -FilePath (Join-Path $work "test.cer") -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
    $out = & C:\sdk\signtool.exe sign /fd SHA256 /sha1 $cert.Thumbprint $msix 2>&1
    Log ("signtool: " + ($out -join " | "))
    if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }

    $t = Measure-Command { Add-AppxPackage -Path $msix }
    $pkg = Get-AppxPackage -Name NeonTorrent
    $size = (Get-ChildItem $pkg.InstallLocation -Recurse -File | Measure-Object Length -Sum).Sum
    Log ("installed {0} in {1:n1} s, {2:n0} MB on disk" -f $pkg.PackageFullName, $t.TotalSeconds, ($size / 1MB))

    Start-Process ("shell:AppsFolder\{0}!NeonTorrent" -f $pkg.PackageFamilyName)
    Start-Sleep -Seconds 25
    $proc = Get-Process -Name NeonTorrent -ErrorAction SilentlyContinue
    if ($proc) {
        Log ("RUNNING pid {0}, {1:n0} MB, window '{2}'" -f $proc[0].Id, ($proc[0].WorkingSet64 / 1MB), $proc[0].MainWindowTitle)
    } else {
        Log "NOT RUNNING"
    }
    # MSIX redirects %APPDATA% writes into the package's own LocalCache
    $logs = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages\$($pkg.PackageFamilyName)") -Recurse -Filter error.log -ErrorAction SilentlyContinue)
    $logs += @(Get-Item (Join-Path $env:APPDATA "NeonTorrent\error.log") -ErrorAction SilentlyContinue)
    foreach ($f in $logs) { Log ("error.log ({0}): {1}" -f $f.FullName, (Get-Content $f.FullName -Raw)) }
    $rules = @(Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "*NEON*" })
    Log ("firewall rules: " + (($rules | ForEach-Object { "$($_.DisplayName) $($_.Direction) $($_.Action)" }) -join "; "))

    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save("C:\results\sandbox.png")
} catch {
    Log ("FAIL: " + $_)
} finally {
    Log "end"
    shutdown.exe /s /t 15
}
