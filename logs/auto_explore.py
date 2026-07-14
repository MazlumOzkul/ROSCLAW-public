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
    def grab(pattern):
        m = re.search(pattern, chunk)
        return float(m.group(1)) if m else 0.0
    x = grab(r'x:\s*(-?[\d.e+-]+)')
    # position block'taki ilk x/y/z, sonra orientation blogundaki x/y/z/w - sirayla yakala
    nums = re.findall(r':\s*(-?[\d.e+-]+)', chunk)
    # nums sirasi: [id, pos.x, pos.y, pos.z, ori.x, ori.y, ori.z, ori.w, ...]
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

def goto(target_x, target_y, tol=0.3, max_steps=15):
    for step in range(max_steps):
        x, y, yaw = get_ground_truth()
        dx, dy = target_x - x, target_y - y
        dist = math.hypot(dx, dy)
        print(f"  [adim {step}] konum=({x:.2f},{y:.2f}) yaw={math.degrees(yaw):.0f} hedef=({target_x},{target_y}) mesafe={dist:.2f}", flush=True)
        if dist < tol:
            print(f"  -> HEDEFE ULASILDI", flush=True)
            return True
        desired_yaw = math.atan2(dy, dx)
        yaw_diff = math.degrees(math.atan2(math.sin(desired_yaw - yaw), math.cos(desired_yaw - yaw)))
        if abs(yaw_diff) > 15:
            turn_time = min(abs(yaw_diff) / 40.0, 3.0)  # ~40 derece/s efektif hiz varsayimi
            send(0.0, 0.5 if yaw_diff > 0 else -0.5, turn_time)
        else:
            drive_time = min(dist / 0.15, 4.0)
            send(0.2, 0.0, drive_time)
    print(f"  -> max adim asildi, devam ediliyor", flush=True)
    return False

waypoints = [
    ("kapiya", 0.0, 0.0),
    ("mutfak girisi", 0.3, 0.8),
    ("mutfaga", 1.5, 1.5),
    ("mutfak kosesine", 2.5, 2.5),
    ("mutfaktan cikis", 0.3, 0.8),
    ("yatak odasi girisi", 0.3, -0.8),
    
    ("yatak odasina", 1.5, -1.5),
    ("yatak odasi kosesine", 2.5, -2.5),
    ("yatak odasindan cikis", 0.3, -0.8),
    ("kapiya donus", 0.0, 0.0),
    ("salona geri", -1.5, 0.0),
]

for label, tx, ty in waypoints:
    print(f"=== {label} ({tx},{ty}) ===", flush=True)
    goto(tx, ty)

send(0.0, 0.0, 0.5)
client.terminate()
print("TUM TUR TAMAMLANDI", flush=True)
