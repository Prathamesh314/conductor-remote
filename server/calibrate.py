"""Coordinate calibration helper.

Run this, then hover your mouse over each button you want to remote-control.
The live X/Y under the cursor is printed continuously. Note the numbers for
the "New Chat" button, the input box, etc., and put them in coordinates.json.

    python3 calibrate.py

Press Ctrl-C to quit.
"""

import time

import pyautogui


def main() -> None:
    print("Move your mouse over a target button. Live coordinates below.")
    print("Press Ctrl-C to stop.\n")
    try:
        while True:
            x, y = pyautogui.position()
            print(f"  X: {x:>5}   Y: {y:>5}", end="\r", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
