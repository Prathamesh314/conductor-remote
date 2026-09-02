# Installing Mac Remote on an iPhone

The file to share is **`ios/dist/MacRemote.ipa`**.

> ⚠️ **iOS is not Android.** You cannot tap an `.ipa` in WhatsApp and have it
> install. Every iPhone app must be *code-signed* for the specific device or
> Apple ID that runs it. This `.ipa` is **unsigned** on purpose — the installer
> tools below sign it with the recipient's own free Apple ID at install time.

## Recipient install (Sideloadly — easiest, needs a computer)

1. Send them `MacRemote.ipa` over WhatsApp / AirDrop / email.
2. They install **Sideloadly** on a Mac or Windows PC: <https://sideloadly.io>
3. Plug the iPhone into that computer with a cable.
4. Open Sideloadly, drag in `MacRemote.ipa`, enter their **Apple ID**, click
   **Start**. (Apple ID is only used to sign locally; a free account works.)
5. On the iPhone: **Settings → General → VPN & Device Management** → tap the
   developer profile (the Apple ID) → **Trust**.
6. Launch **Mac Remote**.

## Recipient install (AltStore — no cable after setup)

Use <https://altstore.io> if they prefer wireless re-signing. Same idea: it
signs the `.ipa` with their Apple ID and installs it.

## Notes / limitations

- **7-day expiry:** apps signed with a *free* Apple ID stop opening after 7 days
  and must be re-installed. A paid Apple Developer account ($99/yr) extends this
  to 1 year.
- **3 apps max** per free Apple ID sideloaded at once.
- **First launch** may need the Trust step (5 above) before iOS lets it open.
- The app talks to your Mac over `ws://` on your Tailnet, so the iPhone must be
  on the same Tailscale network as the Mac. Enter the Mac's `100.x.x.x`
  Tailscale IP and the emailed auth code on the connect screen.

## Want a tap-a-link install instead of a file?

That requires **TestFlight** (Apple's official beta channel): a paid Apple
Developer account, upload the build to App Store Connect, then invite testers
with a link — no cable, no 7-day expiry. Say the word and I'll set up the
`xcodebuild` export + upload steps for that route.

## Rebuild the .ipa

```bash
cd ios
./build-ipa.sh      # regenerates the project and writes dist/MacRemote.ipa
```
