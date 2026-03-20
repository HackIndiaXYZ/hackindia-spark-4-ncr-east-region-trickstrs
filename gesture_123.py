import cv2
import mediapipe as mp
import requests
import pygetwindow as gw
import pyautogui
import pyperclip
import time
import tkinter as tk
import threading
import pystray
import webbrowser
from PIL import Image, ImageDraw
from tkinter import filedialog
from tkinter import simpledialog
from PIL import ImageGrab
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python import BaseOptions

import sys
import os

# def ask_username():

#     root = tk.Tk()
#     root.withdraw()

#     name = simpledialog.askstring("Username", "Enter your name")

#     if not name:
#         name = "User"

#     return name


# USER_NAME = ask_username()


USER_NAME = os.getlogin()

print("USER =", USER_NAME)

def ask_server():
    root = tk.Tk()
    root.withdraw()
    server = simpledialog.askstring(
        "Server (LAN)",
        "Enter LAN server base URL (example: http://192.168.1.10:5000)"
    )
    if not server:
        server = "http://127.0.0.1:5000"
    return server.strip().rstrip("/")


SERVER = ask_server()

def register_user():

    try:

        url = SERVER + "/register"

        requests.post(
            url,
            data={"user": USER_NAME}
        )

        print("Registered on server")

    except Exception as e:
        print("Register error:", e)


register_user()

def get_model_path():

    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS   # PyInstaller temp folder
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    path = os.path.join(base_path, "hand_landmarker.task")

    print("MODEL PATH =", path)

    if not os.path.exists(path):
        print("Model not found at:", path)
        raise FileNotFoundError("hand_landmarker.task not found")

    return path

# def heartbeat():

    # while True:

    #     try:

    #         requests.post(
    #             SERVER + "/heartbeat",
    #             data={"user": USER_NAME},
    #             timeout=2
    #         )

    #     except:
    #         pass

    #     time.sleep(2)

def get_base_path():

    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return base_path


model_path = get_model_path()

BaseOptions = python.BaseOptions
HandLandmarker = vision.HandLandmarker
HandLandmarkerOptions = vision.HandLandmarkerOptions
VisionRunningMode = vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
    num_hands=1
)

landmarker = HandLandmarker.create_from_options(options)

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

frame_id = 0
cooldown_until = 0

prev_state = "none"
cooldown = 0
gesture_lock = False

selected_file = None

def take_screenshot():

    t = int(time.time())

    base = get_base_path()

    save_dir = os.path.join(base, "data", "ss")

    os.makedirs(save_dir, exist_ok=True)

    path = os.path.join(save_dir, f"screen_{t}.png")

    img = ImageGrab.grab(all_screens=True)

    img.save(path)

    return path

def get_current_url():

    title = get_active_window()

    if not any(x in title for x in ["chrome", "edge"]):
        print("Browser not active")
        return None

    time.sleep(0.3)

    # focus address bar
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.3)

    # copy url
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.3)

    url = pyperclip.paste()

    print("URL:", url)

    return url


def check_url():

    try:

        r = requests.get(
            SERVER + "/get_url/" + USER_NAME,
            timeout=5
        )

        data = r.json()

        if data and "url" in data:

            url = data["url"]

            print("Opening URL:", url)

            webbrowser.open(url)

    except Exception as e:
        print("check_url error:", e)

def get_active_window():

    win = gw.getActiveWindow()

    if win:
        return win.title.lower()

    return ""


# def choose_user_popup(users):

    # selected = {"name": None}

    # def select(name):
    #     selected["name"] = name
    #     root.destroy()

    # root = tk.Tk()
    # root.title("Select User")

    # tk.Label(root, text="Send to:").pack()

    # for u in users:
    #     name = u["name"]
    # status = u["status"]

    # text = f"{name} ({status})"

    # tk.Button(
    #     root,
    #     text=text,
    #     width=25,
    #     command=lambda x=name: select(x)
    # ).pack()

    # root.mainloop()

    # return selected["name"]


# def upload_data():

#     title = get_active_window()

#     l = SERVER + "/upload"

#     ---------- take screenshot first ----------

#     path = take_screenshot()

#     print("Screenshot saved:", path)

#     ---------- get users ----------

#     users = get_users()

#     if not users:
#         print("No users")
#         return

#     ---------- popup after screenshot ----------

#     target = choose_user_popup(users)

#     if not target:
#         print("No target selected")
#         return

#     print("Sending to:", target)

#     ---------- browser case ----------

    # if any(x in title for x in ["chrome", "edge", "firefox", "brave", "opera", "search", "google"]):

    #     text = get_current_url()

    #     if not text:
    #         print("No URL detected")
    #         return

    #     t = int(time.time())

    #     files = {
    #         "file": (f"url_{t}.txt", text)
    #     }

    #     r = requests.post(
    #         url,
    #         files=files
    #         data={
    #             "user": USER_NAME,
    #             "target": target
    #         }
    #     )

    #     print(r.text)

    # # ---------- screenshot send ----------

    # else:

    #     with open(path, "rb") as f:

    #         files = {"file": f}

    #         r = requests.post(
    #             url,
    #             files=files
    #         )

    #     print("Uploaded")

def upload_data():

    title = get_active_window()

    print("Active:", title)

    # ---------- if browser ----------
    if any(x in title for x in ["chrome", "edge"]):

        url = get_current_url()

        if not url:
            print("No URL")
            return

        try:

            requests.post(
                SERVER + "/send_url",
                json={
                    "from": USER_NAME,
                    "url": url
                },
                timeout=5
            )

            print("URL sent")

        except Exception as e:
            print("URL send error:", e)

        return

    # ---------- else screenshot ----------

    path = take_screenshot()

    try:

        with open(path, "rb") as f:

            files = {"file": f}

            requests.post(
                SERVER + "/upload",
                files=files,
                timeout=10
            )

        print("Screenshot uploaded")

    except Exception as e:
        print("Upload error:", e)


def on_exit(icon, item):
    icon.stop()
    import os
    os._exit(0)


# def get_users():

    # url = SERVER + "/files"

    # try:
    #     r = requests.get(url, timeout=5)

    #     if r.status_code != 200:
    #         print("Server error")
    #         return []
        
    #     data = r.json()

    #     users = data.get("users", [])

    #     print("Users on server:", users)

    #     return users

    # except Exception as e:
    #     print("ERROR getting users:", e)
    #     return []
    

# def receive_data():

    # try:

    #     # get file list
    #     r = requests.get(SERVER + "/files", timeout=5)

    #     if r.status_code != 200:
    #         print("Server error")
    #         return

    #     data = r.json()

    #     files = data.get("files", [])

    #     if not files:
    #         print("No files")
    #         return


    #     # take first file
    #     name = files[0]

    #     print("Downloading:", name)


    #     # download
    #     url = SERVER + "/download/" + name

    #     r2 = requests.get(url, timeout=10)

    #     if r2.status_code != 200:
    #         print("Download failed")
    #         return


    #     base_path = get_base_path()

    #     save_name = os.path.join(base_path, name)

    #     with open(save_name, "wb") as f:
    #         f.write(r2.content)

    #     print("Saved:", save_name)


    #     # delete from server (only one time receive)
    #     requests.post(SERVER + "/delete/" + name)

    #     print("Deleted from server")


    # except Exception as e:
    #     print("Receive error:", e)


def receive_data():

    try:

        # First try receiving URL via legacy queue.
        # Newer servers deliver URLs via /next, but this client uses /files.
        # This fallback ensures the URL gets opened immediately.
        try:
            r_url = requests.get(
                SERVER + "/get_url/" + USER_NAME,
                timeout=5
            )
            info = r_url.json() if r_url.status_code == 200 else {}
            url = (info.get("url") or "").strip() if isinstance(info, dict) else ""
            if url:
                print("Opening received URL:", url)
                webbrowser.open(url, new=2)
                return
        except Exception as e:
            print("URL receive fallback error:", e)

        r = requests.get(SERVER + "/files", timeout=5)

        if r.status_code != 200:
            print("Server error")
            return

        data = r.json()

        files = data.get("files", [])

        if not files:
            print("No files")
            return


        name = files[0]

        print("Downloading:", name)


        r2 = requests.get(SERVER + "/download/" + name, timeout=10)

        if r2.status_code != 200:
            print("Download failed")
            return


        base_path = get_base_path()

        save = os.path.join(base_path, name)

        with open(save, "wb") as f:
            f.write(r2.content)

        print("Saved:", save)

        # If this is a URL payload saved as a text file,
        # open it automatically.
        try:
            lower = name.lower()
            if lower.endswith(".txt") or lower.startswith("url_"):
                content = (r2.text or "").strip()
                if content.startswith("http://") or content.startswith("https://"):
                    print("Opening received URL:", content)
                    webbrowser.open(content, new=2)
        except Exception:
            pass


        # delete after receive
        requests.post(SERVER + "/delete/" + name)

        print("Deleted from server")


    except Exception as e:
        print("Receive error:", e)


def run_gesture():

    global prev_state, frame_id, cooldown_until

    print("Gesture thread started")

    while True:

        try:

            success, img = cap.read()

            if not success:
                time.sleep(0.01)
                continue

            cv2.putText(
                img,
                f"State: {prev_state}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2
            )

            cv2.imshow("Gesture Camera", img)

            key = cv2.waitKey(1) & 0xFF

            if key == 27 or key == ord('q'):
                print("Exiting...")
                break

            if time.time() < cooldown_until:
                prev_state = "none"
                continue

            frame_id += 1

            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=img
            )

            result = landmarker.detect_for_video(mp_image, frame_id)

            if not result.hand_landmarks:
                prev_state = "none"
                continue

            hand = result.hand_landmarks[0]

            lmList = []

            h, w, _ = img.shape

            for id, lm in enumerate(hand):
                cx, cy = int(lm.x * w), int(lm.y * h)
                lmList.append((id, cx, cy))

            # -------- distance check (LESS STRICT) --------

            x0, y0 = lmList[0][1], lmList[0][2]
            x9, y9 = lmList[9][1], lmList[9][2]

            hand_size = abs(y0 - y9)

            if hand_size < 60:   # was 95 (too strict)
                prev_state = "none"
                continue

            tipIds = [4, 8, 12, 16, 20]

            fingers = []

            if lmList[4][1] > lmList[3][1]:
                fingers.append(1)
            else:
                fingers.append(0)

            for i in range(1, 5):
                if lmList[tipIds[i]][2] < lmList[tipIds[i]-2][2]:
                    fingers.append(1)
                else:
                    fingers.append(0)

            count = fingers.count(1)

            if fingers == [1,0,0,0,0]:
                state = "thumb"

            elif count == 2:
                state = "two"

            elif count == 5:
                state = "open"

            else:
                state = "none"

            # -------- trigger --------

            if state != prev_state:

                if state in ["none", "open"]:
                    prev_state = state
                    continue

                print("STATE:", state)

                if state == "thumb":

                    print("UPLOAD")

                    threading.Thread(
                        target=upload_data,
                        daemon=True
                    ).start()

                    cooldown_until = time.time() + 1.2
                    prev_state = "none"
                    continue

                elif state == "two":

                    print("RECEIVE")

                    threading.Thread(
                        target=receive_data,
                        daemon=True
                    ).start()

                    cooldown_until = time.time() + 1.2
                    prev_state = "none"
                    continue

            prev_state = state

            time.sleep(0.005)   # important for smooth camera

        except Exception as e:
            print("ERROR:", e)

    cap.release()
    cv2.destroyAllWindows()
    os._exit(0)

def heartbeat():

    while True:

        try:

            requests.post(
                SERVER + "/heartbeat",
                json={"name": USER_NAME},
                timeout=2
            )

        except Exception as e:
            print("Heartbeat error:", e)

        time.sleep(2)


def create_icon():

    image = Image.new("RGB", (64, 64), (0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rectangle((16, 16, 48, 48), fill=(0, 255, 0))

    return image


def tray():

    icon = pystray.Icon(
        "GestureApp",
        create_icon(),
        menu=pystray.Menu(
            pystray.MenuItem("Exit", on_exit)
        ),
    )

    icon.run()

hb = threading.Thread(target=heartbeat)
hb.daemon = True
hb.start()

try:

    gesture_thread = threading.Thread(target=run_gesture)
    gesture_thread.start()

    gesture_thread.join()

except KeyboardInterrupt:
    print("Force exit (Ctrl+C)")
    cap.release()
    cv2.destroyAllWindows()
    os._exit(0)

# tray()