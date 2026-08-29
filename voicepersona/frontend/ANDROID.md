# VoxPersona Android app

The web app is wrapped with **Capacitor** as a native Android app (`com.voxpersona.app`).

## How it works

1. Install the APK on your phone.
2. First screen asks for your **cPanel website URL** (where VoxPersona is hosted), e.g. `https://yourdomain.com`.
3. Then log in / create account as usual.
4. Microphone is used for Family conversation and Talk with program.

The PHP backend still runs on your shared hosting — the Android app is the mobile client.

## Build APK (on a machine with Android SDK)

```bash
cd voicepersona/frontend
npm install
npm run android:apk
```

Debug APK output:

`android/app/build/outputs/apk/debug/app-debug.apk`

## Install on phone

1. Copy `app-debug.apk` to your Android phone.
2. Enable **Install from unknown sources** / allow the file manager.
3. Open the APK and install.
4. Launch **VoxPersona** → enter your hosted site URL → log in.

## Open in Android Studio

```bash
cd voicepersona/frontend
npm run cap:sync
npm run android:open
```

Then use **Build → Build Bundle(s) / APK(s) → Build APK(s)** for a release build (sign with your keystore for Play Store).

## Notes

- Host the web/API on cPanel first (upload the cPanel zip).
- Use **https://** for the server URL when possible.
- Chrome WebView is used inside the app; speech recognition works best on up-to-date Android WebView.
