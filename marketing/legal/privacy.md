# NEON Torrent Privacy Policy

**Effective date:** {{EFFECTIVE_DATE}}

This policy explains what information NEON Torrent ("NEON") handles when you use the Windows app and the NEON website. The app has no account and sends no usage analytics or telemetry. It only makes the connections listed below.

## Connections the app makes

- **Peers and trackers of your torrents.** NEON connects to the trackers, peers and web seeds of the torrents you add, and looks up tracker host names through your normal DNS resolver. Peers in a swarm can see your IP address and which torrent you are sharing; that is how BitTorrent works.
- **Torrent links you add.** When you paste an HTTP(S) link to a .torrent file, NEON downloads the file from that address.
- **Your router.** While "Accept incoming peers" is on (the default), NEON asks your router to forward a port using UPnP or NAT-PMP.
- **DHT, Local Peer Discovery and FLASH mode.** File-only mode is on by default and turns DHT and Local Peer Discovery off. If you turn DHT on, turn File-only mode off, or use FLASH mode, NEON also contacts DHT nodes and announces your torrents on your local network. FLASH mode also adds a few public booster trackers.
- **Shield lists.** The Shield downloads public lists of VPN and datacenter IP ranges (the X4BNet lists, from raw.githubusercontent.com, about once a day) and the iptoasn.com network dataset (about once a week). These are plain downloads: those servers see your IP address and the request, not your torrents.
- **VirusTotal, only if you add your own API key.** With a key entered and scans on, NEON sends the SHA-256 hash of up to 8 programs or scripts in a finished download to VirusTotal, together with your key. It sends hashes, not files. VirusTotal's own terms and privacy policy apply.
- **Antivirus on your PC.** NEON reads Malwarebytes' detection records on your PC to learn which IP addresses and trackers to block, and asks Microsoft Defender on your PC to scan finished downloads. NEON itself sends nothing for these. Defender's cloud protection and sample submission settings in Windows Security apply as they do to any file.
- **Microsoft Store.** The Store installs and updates the app under Microsoft's terms and privacy statement.
- **Pro licence keys.** Activating a Pro licence key checks it with Dodo Payments. {{LICENCE_CHECK_DETAILS}}

## Information stored on your PC

NEON keeps these files on your PC: settings (including your VirusTotal key, if you entered one), torrent resume data, per-torrent settings, Shield blocks learned from Malwarebytes, the cached network database, and an error log. The folder is %APPDATA%\NeonTorrent, or for the Microsoft Store version %LOCALAPPDATA%\Packages\NeonTorrent_…\LocalCache\Roaming\NeonTorrent.

To delete this data, close NEON and delete that folder; uninstalling the Store version also removes its folder. Your downloaded files are kept in your download folder until you delete them.

## Website

The website is hosted on Cloudflare Pages, so Cloudflare processes your IP address and requests to deliver the pages. Cloudflare Web Analytics counts visits without cookies.

## Purchases

Dodo Payments sells NEON Pro as merchant of record: it collects your payment and billing details, handles tax, and applies its own privacy policy. We receive the details needed to issue and support your licence, such as your email address, country and the plan you bought.

## Email

If you email us, we use your address and message to reply, and keep them as long as needed for support, refunds or legal obligations.

## Your rights

Depending on where you live, you may have the right to access, correct or delete personal information we hold about you, to withdraw consent, and to complain to a data protection authority. This includes rights under the EU and UK GDPR and India's Digital Personal Data Protection Act, 2023. To make a request, write to {{CONTACT_EMAIL}}. We will answer as the applicable law requires.

## Changes

If this policy changes, we will publish the new version on this page with a new effective date.

## Contact

Privacy contact: {{CONTACT_EMAIL}}
Owner: {{OWNER_NAME}}
Postal address: {{POSTAL_ADDRESS}}
