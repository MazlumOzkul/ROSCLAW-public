import roslibpy, time, math, subprocess, re, sys

def get_ground_truth():
    """WSL2 icindeki gz topic'ten robotun GERCEK (odom drift'siz) pozisyonunu al."""
    out = subprocess.run(
        ["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c",
         "source /opt/ros/jazzy/setup.bash && timeout 3 gz topic -e -t /world/rosclaw_world/pose/info -n 1 2>&1"],
        capture_output=True, text=True, timeout=15
    ).stdout
    idx = out.find('name: "turtlebot3_manipulation"')
    chunk = out[idx:idx+500]
    nums = re.findall(r':\s*(-?[\d.e+-]+)', chunk)
    pos_x, pos_y = float(nums[1]), float(nums[2])
    ori_x, ori_y, ori_z, ori_w = float(nums[4]), float(nums[5]), float(nums[6]), float(nums[7])
    yaw = math.atan2(2*(ori_w*ori_z + ori_x*ori_y), 1 - 2*(ori_y**2 + ori_z**2))
    return pos_x, pos_y, yaw

client = roslibpy.Ros(host='localhost', port=9090)
client.run()
time.sleep(1)
pub = roslibpy.Topic(client, '/cmd_vel', 'geometry_msgs/msg/TwistStamped')

def send(lin, ang, dur):
    msg = roslibpy.Message({'twist': {'linear': {'x': lin, 'y':0.0,'z':0.0}, 'angular': {'x':0.0,'y':0.0,'z': ang}}})
    end = time.time() + dur
    while time.time() < end:
        pub.publish(msg); time.sleep(0.1)
    stop_msg = roslibpy.Message({'twist': {'linear': {'x': 0.0,'y':0.0,'z':0.0}, 'angular': {'x':0.0,'y':0.0,'z':0.0}}})
    for _ in range(5):
        pub.publish(stop_msg); time.sleep(0.1)

def recover():
    print("  !! SIKISMA TESPIT EDILDI -> geri git + don kurtarma", flush=True)
    send(-0.15, 0.0, 1.5)
    send(0.0, 0.5, 1.0)

def goto(target_x, target_y, tol=0.3, max_steps=25):
    history = []
    for step in range(max_steps):
        x, y, yaw = get_ground_truth()
        dx, dy = target_x - x, target_y - y
        dist = math.hypot(dx, dy)
        print(f"  [adim {step}] konum=({x:.2f},{y:.2f}) yaw={math.degrees(yaw):.0f} hedef=({target_x},{target_y}) mesafe={dist:.2f}", flush=True)
        if dist < tol:
            print(f"  -> HEDEFE ULASILDI", flush=True)
            return True
        history.append((x, y))
        if len(history) >= 4:
            recent = history[-4:]
            moved = math.hypot(recent[-1][0]-recent[0][0], recent[-1][1]-recent[0][1])
            if moved < 0.08:
                recover()
                history = []
                continue
        desired_yaw = math.atan2(dy, dx)
        yaw_diff = math.degrees(math.atan2(math.sin(desired_yaw - yaw), math.cos(desired_yaw - yaw)))
        if abs(yaw_diff) > 15:
            turn_time = min(abs(yaw_diff) / 40.0, 3.0)
            send(0.0, 0.5 if yaw_diff > 0 else -0.5, turn_time)
        else:
            drive_time = min(dist / 0.15, 3.0)
            send(0.15, 0.0, drive_time)
    print(f"  -> max adim asildi, devam ediliyor", flush=True)
    return False

waypoints = [
    ("kapiya", 0.0, 0.0),
    ("mutfak girisi", 0.3, 0.5),
    ("mutfak ic", 1.0, 1.0),
    ("mutfaga", 1.5, 1.5),
    ("mutfak kosesi ust", 2.5, 2.5),
    ("mutfak kosesi alt", 2.5, 0.3),
    ("mutfaktan cikis", 1.0, 0.3),
    ("orta kapi", 1.5, 0.0),
    ("yatak odasi girisi", 1.5, -0.5),
    ("yatak odasina", 1.5, -1.5),
    ("yatak odasi kosesi ust", 2.5, -0.3),
    ("yatak odasi kosesi alt", 2.5, -2.5),
    ("yatak odasindan cikis", 1.0, -0.5),
    ("kapiya donus", 0.0, 0.0),
    ("salona geri", -1.5, 0.0),
]

for label, tx, ty in waypoints:
    print(f"=== {label} ({tx},{ty}) ===", flush=True)
    goto(tx, ty)

send(0.0, 0.0, 0.5)
client.terminate()
print("TUM TUR TAMAMLANDI", flush=True)
