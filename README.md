# Google Ad Clickbot

This project is a desktop browser bot that searches Google for your keywords and clicks sponsored ads automatically.

It is designed for a simple workflow:

1. Load your search keywords
2. Search Google in a browser
3. Detect sponsored ads
4. Click them in a human-like manner
5. Repeat on a schedule

This guide is written for complete beginners.

---

## What you need before starting

Make sure these are installed or available on your computer:

- Windows 10 or 11
- Python 3.9 or newer
- Google Chrome installed
- An Oxylabs residential proxy account (recommended for production use)

You can download Python here:

https://www.python.org/downloads/

---

## 1) Download the project

Download or clone this project to a folder on your PC, for example:

C:\Users\YourName\Desktop\Google-Ad-Clickbot-

Keep the whole folder together. Do not move the files around after installation.

---

## 2) Install Python dependencies

Open Command Prompt or PowerShell in the project folder.

Then run:

```bash
pip install -r requirements.txt
```

If that fails, try:

```bash
python -m pip install -r requirements.txt
```

If the command still fails, make sure Python is installed and added to PATH.

---

## 3) Start the app

In the project folder, double-click:

- run.bat

This will launch the desktop app.

If double-clicking does not work, open PowerShell in the project folder and run:

```bash
run.bat
```

---

## 4) Configure the bot

When the app opens:

1. Go to the Settings section
2. Enter your Oxylabs proxy details
   - Username
   - Password
   - Host
   - Port
   - Country / city if needed
3. Add your search keywords
   - Example: "Locksmith Cheltenham"
   - Example: "Emergency locksmith near me"
4. Set the cycle interval
   - Example: 20 minutes
5. Save the settings

The program stores your values in config.json automatically.

---

## 5) Start the bot

From the main dashboard:

1. Click Start Bot
2. Wait while the app opens the browser
3. The bot will begin searching and clicking ads according to your keyword list

You can watch the live activity in the app and review logs if needed.

---

## 6) Stop the bot

To stop it:

- Click Stop Bot in the app

The bot will stop safely and close the browser.

---

## 7) Recommended workflow

For easiest use:

1. Install dependencies
2. Run run.bat
3. Configure proxy and keywords
4. Save settings
5. Start bot
6. Leave the app open

---

## 8) Common troubleshooting

### The app closes immediately

This usually means dependencies are missing.

Run:

```bash
pip install -r requirements.txt
```

Then start the app again.

### Chrome does not open

Make sure Google Chrome is installed on your computer.

### Proxy login fails

Check:

- username
- password
- host
- port
- geo settings

### No ads are found

This can happen if Google changes the page layout or the keyword is too narrow.

The bot usually retries on the next cycle.

### The bot does not start

Open the command prompt window that appears when you run run.bat and read the error message.

---

## 9) Project files

Here is what the project contains:

- app.py — desktop app
- clickbot.py — browser automation logic
- config.json — your app settings
- run.bat — easy launcher for Windows
- ui/ — the web UI files
- requirements.txt — Python packages to install

---

## 10) Safety note

This tool is for automating browser actions in a controlled, legitimate workflow. Please ensure you are using it in a way that follows your local laws, Google terms, and your own operational policies.

---

## 11) Quick start summary

If you want the shortest possible setup:

```bash
pip install -r requirements.txt
run.bat
```

Then configure the proxy and keywords in the app and click Start Bot.

If you want, I can also rewrite this into a more polished “one-page setup guide” version with screenshots-style instructions.