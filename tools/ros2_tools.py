"""
ROSClaw ROS2 Arac Seti - A katmani (affordance manifest)

8 temel arac + ek araclar.
WSL2/ROS2/rosbridge kurulana kadar stub modda calisir (baglanti yok, sadece manifest).
rosbridge websocket portu (varsayilan 9090) WSL2 icinde acildiginda,
Windows'tan "localhost:9090" uzerinden erisilebilir (WSL2 mirrored networking ile).
"""

import json
import base64
from typing import Optional
import roslibpy
from core.observation import ObservationNormalizer


class ROS2ToolRegistry:
    """
    ROSClaw sozlesmesinin A (Affordance) katmani.
    Her arac validator'dan gectikten sonra calisir.
    """

    def __init__(self, ros_host: str = "localhost", ros_port: int = 9090):
        self.ros_host = ros_host
        self.ros_port = ros_port
        self.client = None
        self._connected = False
        self._latest_scan = None
        self._scan_topic = None
        self._normalizer = ObservationNormalizer()
        # AgentCore tarafindan atanir - /scan verisi geldikce (LLM'den
        # BAGIMSIZ, kendi callback thread'inde) cagirilir. "Brain-Cerebellum"
        # ayriminin temeli: yavas LLM dongusunu beklemeden aninda tepki.
        self.reflex_callback = None

    def connect(self) -> bool:
        """rosbridge'e baglan."""
        try:
            self.client = roslibpy.Ros(host=self.ros_host, port=self.ros_port)
            self.client.run(timeout=5)
            self._connected = self.client.is_connected
            if self._connected:
                print(f"[OK] ROS2 baglantisi: {self.ros_host}:{self.ros_port}")
                self._subscribe_scan_background()
            return self._connected
        except Exception as e:
            print(f"[ERR] ROS2 baglanti hatasi: {e}")
            self._connected = False
            return False

    def _subscribe_scan_background(self, topic: str = "/scan"):
        """
        /scan'e KALICI (tek seferlik degil) abone olur. Iki amaca hizmet
        eder: (1) get_front_distance() her cagrildiginda en son veriyi
        aninda dondurur - her seferinde yeniden subscribe+timeout beklemez,
        (2) reflex_callback atanmissa, her yeni tarama geldiginde ONA da
        haber verilir - boylece kritik yakinlikta LLM'i hic beklemeden
        e-stop tetiklenebilir. Robotta /scan yoksa (lazer siz robot) sessizce
        gecilir, hata degildir.
        """
        try:
            self._scan_topic = roslibpy.Topic(self.client, topic, "sensor_msgs/msg/LaserScan")
            self._scan_topic.subscribe(self._on_scan_message)
        except Exception as e:
            print(f"[WARN] /scan aboneligi kurulamadi (lazer yok olabilir): {e}")

    def _on_scan_message(self, msg):
        self._latest_scan = msg
        if self.reflex_callback:
            front = self._front_distance_from_scan(msg)
            if front is not None:
                self.reflex_callback(front)

    def _front_distance_from_scan(self, raw_scan) -> Optional[float]:
        try:
            normalized = self._normalizer.normalize("/scan", raw_scan)
            return normalized.get("front_distance")
        except Exception:
            return None

    def get_front_distance(self) -> Optional[float]:
        """En son bilinen lazer taramasina gore ondeki en yakin engel mesafesi (metre). Veri yoksa None."""
        if self._latest_scan is None:
            return None
        return self._front_distance_from_scan(self._latest_scan)

    def disconnect(self):
        """
        Sadece bu websocket baglantisini kapatir (client.close()).
        BILINCLI OLARAK client.terminate() KULLANILMIYOR: terminate() alttaki
        paylasilan Twisted "reactor" event loop'unu tamamen durdurur ve
        Twisted, ayni process icinde durmus bir reactor'u YENIDEN
        BASLATAMAZ (twisted.internet.error.ReactorNotRestartable). Bu da
        ROSClaw'in calisirken baska bir robota gecmesini (switch_robot)
        imkansiz hale getirir. close() ise sadece bu baglantiyi kapatir,
        reactor calismaya devam eder, boylece yeni bir ROS2ToolRegistry
        ile hemen yeniden baglanilabilir.
        """
        if self._scan_topic:
            try:
                self._scan_topic.unsubscribe()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self._connected = False

    # -- 1. ros2_publish -----------------------------------------
    def ros2_publish(self, topic: str, msg: dict,
                     msg_type: str = "geometry_msgs/Twist") -> dict:
        """Bir topic'e mesaj yayinla."""
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            publisher = roslibpy.Topic(self.client, topic, msg_type)
            publisher.publish(roslibpy.Message(msg))
            return {"status": "ok", "topic": topic, "msg": msg}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 2. ros2_subscribe -----------------------------------------
    def ros2_subscribe(self, topic: str, timeout: float = 3.0, msg_type: str = None) -> dict:
        """
        Bir topic'ten tek mesaj oku. msg_type verilmezse rosbridge'in tip
        auto-detect'ine guvenilir - bu kucuk/basit mesajlarda (odom, scan)
        calisir ama BUYUK BINARY mesajlarda (orn. kamera Image, ~1.2MB
        base64) SESSIZCE BASARISIZ olabiliyor. Boyle mesajlar icin msg_type
        MUTLAKA acikca verilmeli (bkz. ros2_camera).
        """
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        result = {"data": None}
        try:
            subscriber = roslibpy.Topic(self.client, topic, msg_type)

            def callback(msg):
                result["data"] = msg
                subscriber.unsubscribe()

            subscriber.subscribe(callback)
            import time
            start = time.time()
            while result["data"] is None and time.time() - start < timeout:
                time.sleep(0.1)

            if result["data"] is None:
                return {"status": "timeout", "topic": topic}
            return {"status": "ok", "topic": topic, "data": result["data"]}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 3. ros2_service -----------------------------------------
    def ros2_service(self, service: str, request: dict = None,
                     service_type: str = "std_srvs/Trigger", timeout: float = 5.0) -> dict:
        """Bir ROS2 servisini cagir ve yaniti bekler (dogru JSON-serilestirilebilir dict olarak)."""
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            import threading
            service_client = roslibpy.Service(self.client, service, service_type)
            result = {"data": None}
            done = threading.Event()

            def callback(resp):
                # roslibpy.ServiceResponse bir UserDict - JSON'a cevrilebilmesi
                # icin (hem gateway'den gecerken hem uretilen kodda) duz dict'e
                # cevirmek gerekiyor, ham nesneyi dondurmek json.dumps'ta patlar.
                result["data"] = dict(resp)
                done.set()

            service_client.call(roslibpy.ServiceRequest(request or {}), callback)
            if not done.wait(timeout):
                return {"status": "timeout", "service": service}
            return {"status": "ok", "service": service, "response": result["data"]}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 4. ros2_action -----------------------------------------
    def ros2_action(self, action: str, goal: dict,
                     action_type: str = "control_msgs/action/FollowJointTrajectory",
                     timeout: float = 10.0) -> dict:
        """
        Herhangi bir ROS2 action'ina hedef gonderir ve sonucu bekler (kol
        kontrolu icin FollowJointTrajectory/GripperCommand, Nav2 icin
        NavigateToPose gibi). roslibpy.ActionClient uzerinden calisir -
        Faz A/B testlerinde FollowJointTrajectory ile dogrulanmis pattern.
        """
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            import threading
            client = roslibpy.ActionClient(self.client, action, action_type)
            result_box = {}
            done = threading.Event()

            def _on_result(r):
                result_box["result"] = r
                done.set()

            def _on_error(e):
                result_box["error"] = str(e)
                done.set()

            client.send_goal(
                roslibpy.Message(goal),
                resultback=_on_result,
                feedback=lambda f: None,
                errback=_on_error,
            )
            if not done.wait(timeout):
                return {"status": "timeout", "action": action}
            if "error" in result_box:
                return {"status": "error", "action": action, "reason": result_box["error"]}
            return {"status": "ok", "action": action, "result": result_box["result"]}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 4b. ros2_move_arm_to_pose ---------------------------------
    def ros2_move_arm_to_pose(self, x: float, y: float, z: float,
                               duration_sec: float = 2.0) -> dict:
        """
        Kolun ucunu (end_effector) base_link cercevesinde verilen (x,y,z)
        metre konumuna goturur. MoveIt2 bu robot icin vendor'un config
        paketindeki bir hatadan dolayi calismadigindan (bkz. arm_kinematics.py
        docstring), kendi sayisal IK cozumumuzu kullanir, sonucu
        FollowJointTrajectory action'ina gonderir.
        """
        from tools.arm_kinematics import inverse_kinematics
        ik = inverse_kinematics(x, y, z)
        if not ik["success"]:
            return {"status": "error", "reason": ik["reason"]}
        goal = {
            "trajectory": {
                "joint_names": ["joint1", "joint2", "joint3", "joint4"],
                "points": [{
                    "positions": ik["joints"], "velocities": [],
                    "time_from_start": {"sec": int(duration_sec), "nanosec": 0},
                }],
            }
        }
        result = self.ros2_action(
            "/arm_controller/follow_joint_trajectory", goal,
            "control_msgs/action/FollowJointTrajectory",
            timeout=duration_sec + 5.0)
        if result["status"] == "ok":
            result["target"] = {"x": x, "y": y, "z": z}
            result["joints"] = ik["joints"]
        return result

    # -- 4c. ros2_gripper -------------------------------------------
    def ros2_gripper(self, position: float, max_effort: float = 5.0) -> dict:
        """
        Gripper'i acar/kapatir. position: -0.010 (tam kapali) ile 0.019
        (tam acik) arasi metre cinsinden hedef (URDF'teki gripper_left_joint
        limitleri). Pratik kisayollar: 0.019=ac, -0.010=kapat/tut.
        """
        goal = {"command": {"position": position, "max_effort": max_effort}}
        return self.ros2_action(
            "/gripper_controller/gripper_cmd", goal,
            "control_msgs/action/GripperCommand", timeout=5.0)

    # -- 4f. ros2_navigate_to_location / ros2_save_location ----------
    def ros2_navigate_to_location(self, name: str, timeout: float = 90.0) -> dict:
        """
        Kaydedilmis isimli bir konuma (orn. "mutfak", "salon") Nav2 ile
        otonom olarak gider. Konum onceden ros2_save_location ile
        kaydedilmis olmali. Nav2'nin kendi global/yerel costmap tabanli
        yol planlamasi ve engelden kacinmasi kullanilir - bu, sadece
        harita OLARAK BILINEN (SLAM ile kesfedilmis) bolgelerde calisir;
        haritalanmamis bir bolgeye hedef verilirse Nav2 GUVENLI SEKILDE
        planlamayi reddeder (rastgele/tehlikeli bir rotaya girmez).
        """
        from memory.location_store import LocationStore
        store = LocationStore()
        loc = store.get_by_name(name)
        if not loc:
            return {"status": "error", "reason": f"'{name}' adinda kayitli bir konum yok. "
                                                   f"Once ros2_save_location ile kaydet."}

        import math
        goal = {
            "pose": {
                "header": {"frame_id": "map"},
                "pose": {
                    "position": {"x": loc["x"], "y": loc["y"], "z": 0.0},
                    "orientation": {"x": 0.0, "y": 0.0,
                                    "z": math.sin(loc["yaw"] / 2), "w": math.cos(loc["yaw"] / 2)},
                },
            }
        }
        result = self.ros2_action("/navigate_to_pose", goal,
                                   "nav2_msgs/action/NavigateToPose", timeout=timeout)
        if result.get("status") == "ok":
            result["location"] = name
        return result

    def ros2_save_location(self, name: str) -> dict:
        """
        Robotun SU ANKI konumunu (Nav2/AMCL'in 'map' cercevesindeki tahmini,
        /amcl_pose'dan) verilen isimle kaydeder - "burasi mutfak" demek gibi.
        Ayni isim zaten varsa GUNCELLENIR.
        """
        result = self.ros2_subscribe("/amcl_pose", timeout=5.0,
                                      msg_type="geometry_msgs/msg/PoseWithCovarianceStamped")
        if result.get("status") != "ok":
            return {"status": "error",
                    "reason": "Su anki konum (/amcl_pose) alinamadi - Nav2/AMCL calisiyor mu?"}

        import math
        pose = result["data"]["pose"]["pose"]
        x, y = pose["position"]["x"], pose["position"]["y"]
        q = pose["orientation"]
        yaw = math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]),
                          1 - 2 * (q["y"] ** 2 + q["z"] ** 2))

        from memory.location_store import LocationStore
        store = LocationStore()
        store.save(name, x, y, yaw)
        return {"status": "ok", "name": name, "x": x, "y": y, "yaw": yaw}

    # -- 5. ros2_get_param -----------------------------------------
    def ros2_get_param(self, node: str, param: str) -> dict:
        """ROS2 parametre oku."""
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            param_client = roslibpy.Param(self.client, f"{node}/{param}")
            value = param_client.get()
            return {"status": "ok", "node": node, "param": param, "value": value}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 6. ros2_set_param -----------------------------------------
    def ros2_set_param(self, node: str, param: str, value) -> dict:
        """ROS2 parametre yaz."""
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            param_client = roslibpy.Param(self.client, f"{node}/{param}")
            param_client.set(value)
            return {"status": "ok", "node": node, "param": param, "value": value}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 7. ros2_list_topics -----------------------------------------
    def ros2_list_topics(self) -> dict:
        """Mevcut tum topic'leri listele. Robot-agnostik olmayi saglayan kritik arac."""
        if not self._connected:
            return {"status": "error", "reason": "ROS2 bagli degil"}
        try:
            topics = self.client.get_topics()
            return {"status": "ok", "topics": topics, "count": len(topics)}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # -- 9. ros2_topics_with_types --------------------------------
    def ros2_topics_with_types(self) -> dict:
        """
        HIC BILINMEYEN BIR ROBOTUN yeteneklerini kesfetmek icin TEMEL arac.
        Her topic'i mesaj TIPIYLE birlikte dondurur (orn. /cmd_vel ->
        geometry_msgs/msg/TwistStamped). Sadece isim degil, tip de bilinmeden
        dogru mesaj olusturulamaz - bu yuzden hicbir on-ayari olmayan yeni
        bir robotta once bu cagrilmali.
        """
        result = self.ros2_service("/rosapi/topics_and_raw_types", {},
                                    "rosapi_msgs/srv/TopicsAndRawTypes")
        if result.get("status") != "ok":
            return result
        resp = result["response"]
        pairs = dict(zip(resp.get("topics", []), resp.get("types", [])))
        return {"status": "ok", "topics": pairs, "count": len(pairs)}

    # -- 10. ros2_message_details ---------------------------------
    def ros2_message_details(self, message_type: str) -> dict:
        """
        Bir mesaj tipinin TAM alan yapisini (field adlari, alt-tipleri,
        dizi uzunluklari) dondurur - `ros2 interface show` komutunun ROS2
        agenti icin karsiligi. HIC BILINMEYEN bir robotun ozel mesaj
        tipini (orn. Unitree'nin kendi mesaj paketleri) ELLE dokumante
        etmeden, calisirken kesfetmeyi saglar - "her robotta calisma"
        hedefinin temel tasi budur.
        Ornek: ros2_message_details("geometry_msgs/msg/TwistStamped")
        """
        result = self.ros2_service("/rosapi/message_details", {"type": message_type},
                                    "rosapi_msgs/srv/MessageDetails")
        if result.get("status") != "ok":
            return result
        typedefs = result["response"].get("typedefs", [])
        return {"status": "ok", "type": message_type, "typedefs": typedefs}

    # -- 8. ros2_camera -----------------------------------------
    def ros2_camera(self, topic: str = "/camera/image_raw") -> dict:
        """Kamera goruntusu al, base64 olarak dondur."""
        result = self.ros2_subscribe(topic, timeout=5.0, msg_type="sensor_msgs/msg/Image")
        if result["status"] != "ok":
            return result
        return {
            "status": "ok",
            "topic": topic,
            "encoding": "base64",
            "data": result.get("data", {})
        }

    # -- 4d. ros2_detect_object -------------------------------------
    def ros2_detect_object(self, color: str, plane_z: float = 0.0) -> dict:
        """
        Kameradan tek kare alir, verilen renkteki en buyuk nesneyi bulur ve
        base_link cercevesinde tahmini (x,y,z) konumunu dondurur (bkz.
        tools/object_detection.py - tek RGB kameradan yaklasik duzlem-kesisimi
        yontemi, gercek derinti olcumu degil).
        """
        from tools.object_detection import decode_ros_image, find_color_centroid, pixel_to_ground_point

        img_result = self.ros2_camera()
        if img_result.get("status") != "ok":
            return {"found": False, "reason": "Kamera goruntusu alinamadi"}

        info_result = self.ros2_subscribe("/camera/camera_info", timeout=3.0,
                                           msg_type="sensor_msgs/msg/CameraInfo")
        if info_result.get("status") != "ok":
            return {"found": False, "reason": "Kamera kalibrasyonu (camera_info) alinamadi"}

        image = decode_ros_image(img_result["data"])
        centroid = find_color_centroid(image, color)
        if not centroid["found"]:
            return centroid

        point = pixel_to_ground_point(
            centroid["pixel"]["u"], centroid["pixel"]["v"],
            info_result["data"], plane_z)
        if not point["found"]:
            return point

        point["pixel"] = centroid["pixel"]
        point["area_px"] = centroid["area_px"]
        return point

    # -- 4e. ros2_find_object (gercek acik-kelime nesne tanima) ------
    def ros2_find_object(self, description: str) -> dict:
        """
        YOLO-World ile GERCEK, acik-kelime nesne tespiti ("supurge", "bardak",
        "vacuum cleaner" gibi rastgele metin - renk DEGIL, nesne TIPI).
        Depth Anything V2 ile gercek derinlik olcerek 3D konum hesaplar,
        ardindan gripper'in fiziksel acikligina gore TUTULABILIRLIK kontrolu
        yapar (bkz. tools/grasp_planning.py - bu kolda bilek donme ekseni
        olmadigi icin sadece genislik kontrolu yapiliyor, kavrama acisi
        secilemiyor).

        BILINEN SINIRLAMA: bu model gercek fotograflarda dogrulandi (COCO
        test goruntusunde %92 guven), ama Gazebo Sim'in render motoru gercek
        kameralardan cok farkli oldugu icin SIMULASYONDA neredeyse hic
        tespit uretmez - "sim-to-real" farki, kod hatasi degil. Gercek
        robotta/gercek kamerada dogrudan calismasi beklenir.
        """
        from tools.object_recognition import find_object
        from tools.object_detection import decode_ros_image, _CAMERA_POS_BASE, _ROT_BASE_FROM_OPTICAL
        from tools.depth_estimation import estimate_depth_map, depth_at_pixel
        from tools.grasp_planning import estimate_object_width_m, check_graspability
        import numpy as np

        img_result = self.ros2_camera()
        if img_result.get("status") != "ok":
            return {"found": False, "reason": "Kamera goruntusu alinamadi"}
        info_result = self.ros2_subscribe("/camera/camera_info", timeout=3.0,
                                           msg_type="sensor_msgs/msg/CameraInfo")
        if info_result.get("status") != "ok":
            return {"found": False, "reason": "Kamera kalibrasyonu alinamadi"}

        image = decode_ros_image(img_result["data"])
        detection = find_object(image, description)
        if not detection["found"]:
            return detection

        K = info_result["data"]["k"] if "k" in info_result["data"] else info_result["data"]["K"]
        fx, fy, cx, cy = K[0], K[4], K[2], K[5]

        depth_map = estimate_depth_map(image)
        u, v = detection["pixel"]["u"], detection["pixel"]["v"]
        depth_m = depth_at_pixel(depth_map, u, v)

        ray_optical = np.array([(u - cx) * depth_m / fx, (v - cy) * depth_m / fy, depth_m])
        point_base = _CAMERA_POS_BASE + _ROT_BASE_FROM_OPTICAL @ ray_optical

        width_m = estimate_object_width_m(detection["bbox_px"]["width"], depth_m, fx)
        grasp = check_graspability(width_m)

        return {
            "found": True,
            "x": float(point_base[0]), "y": float(point_base[1]), "z": float(point_base[2]),
            "confidence": detection["confidence"],
            "depth_m": depth_m,
            "graspable": grasp["graspable"],
            "reason": grasp.get("reason"),
        }

    # -- Model icin arac aciklamalari -----------------------------------------
    def get_tool_manifest(self, profile: dict = None) -> str:
        """
        ROSClaw sozlesmesinin A (Affordance) katmani. Model bu listeyi gorur.
        `profile` verilirse (aktif robot profili), hareket komutu ornegi ve
        izinli topic listesi o robota gore uyarlanir - boylece ayni prompt
        Gazebo/TurtleBot3, gercek TurtleBot3, Unitree G1 veya baska herhangi
        bir rosbridge robotu icin dogru rehberligi verir.
        """
        movement_style = (profile or {}).get("movement_style", "twist_stamped")

        if movement_style == "unitree_sport":
            hareket_notu = """1. ros2_publish(topic, msg, msg_type)
   - Bu robot (Unitree G1 tarzi) yuksek-seviye "sport" komut arayuzu kullanir.
     Hareket icin /api/sport/request topic'ine JSON istek gonderilir (duz
     Twist/TwistStamped DEGIL). Kesin alan adlari icin once
     ros2_list_topics() ve search_docs("unitree sport request formati") ile
     dogrula. DUSUK SEVIYE /lowcmd topic'ini ASLA kullanma - dogrudan motor
     kontrolu dusme/hasar riski tasir ve allowlist'te olmamali."""
        elif movement_style == "unknown":
            hareket_notu = """1. ros2_publish(topic, msg, msg_type)
   - Bu robotun hareket komut formati henuz bilinmiyor.
   - ZORUNLU KURAL: Bu robot icin ilk ros2_publish cagrindan ONCE, bu gorevde
     DAHA ONCE hic KESIF yapmadiysan (ilk defa bu robotla ugrasiyorsan),
     su iki aracı SIRAYLA cagirmak ZORUNDASIN - "muhtemelen boyledir" diye
     ONCEDEN BILDIGIN bir formati (orn. genel ROS2 egitiminden hatirladigin
     duz Twist) VARSAYARAK DOGRUDAN ros2_publish'e GECME, cunku bu robotun
     GERCEK mesaj tipi TAMAMEN FARKLI/OZEL olabilir (orn. Twist yerine
     TwistStamped, ya da robota ozgu hic bilmedigin bir mesaj paketi):
     a) ros2_topics_with_types() -> tum topic'leri TIPLERIYLE birlikte
        listele (orn. {"/cmd_vel": "geometry_msgs/msg/TwistStamped"}).
        Hareketle ilgili gorunen bir topic bul (cmd_vel, sport, motion,
        move, twist gibi isimler icerebilir).
     b) ros2_message_details(mesaj_tipi) -> o mesajin TAM alan yapisini
        ("ros2 interface show" ile ayni) getirir - iceigindeki her alt-tipi
        de (orn. Twist icindeki linear/angular) gosterir. Boylece hicbir
        yerde dokumante edilmemis bir mesaj formatini bile kesfedebilirsin.
        DONEN alan adlarini AYNEN kullan, tahmin etme.
     c) Gerekirse search_docs() / web_search() ile bu robota ozel ek bilgi ara.
     d) Ancak yukaridakilerden EMIN OLDUKTAN SONRA ros2_publish cagir -
        dogru alan adlarini ros2_message_details ciktisindan al."""
        else:
            hareket_notu = """1. ros2_publish(topic, msg, msg_type)
   - /cmd_vel'e TwistStamped mesaji gonder (robot hareket) - DIKKAT: bu
     Gazebo/ros_gz_bridge kurulumunda /cmd_vel duz Twist DEGIL, TwistStamped
     bekler (hiz alanlari "twist" anahtari altinda olmali, header bos kalabilir)
   - Ornek: ros2_publish("/cmd_vel",
       {"header": {}, "twist": {"linear": {"x": 0.3, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}},
       "geometry_msgs/msg/TwistStamped")"""

        profil_notu = ""
        if profile and profile.get("notes"):
            profil_notu = f"\n\nAKTIF ROBOT NOTU ({profile.get('name', 'bilinmiyor')}): {profile['notes']}"

        return f"""
Kullanilabilir ROS2 araclari:

{hareket_notu}

2. ros2_subscribe(topic, timeout=3.0)
   - Sensor verisi oku (/scan, /odom, /imu)
   - Ornek: ros2_subscribe("/scan")

3. ros2_service(service, request, service_type)
   - ROS2 servisini cagir

4. ros2_action(action, goal)
   - Nav2 navigasyon hedefi gonder

5. ros2_get_param(node, param) / ros2_set_param(node, param, value)
   - ROS2 parametre oku/yaz

6. ros2_list_topics()
   - Mevcut tum topic isimlerini listele

7. ros2_topics_with_types()
   - HIC TANIMADIGIN bir robotu kesfetmenin ilk adimi: her topic'i mesaj
     TIPIYLE birlikte dondurur, orn. {{"/cmd_vel": "geometry_msgs/msg/TwistStamped"}}

8. ros2_message_details(message_type)
   - Bir mesaj tipinin TAM alan yapisini getirir (nested alt-tipler dahil) -
     "ros2 interface show" komutunun karsiligi. Bilmedigin bir mesaj
     formatiyla karsilastiginda ASLA tahmin etme, once bunu cagir.
     Ornek: ros2_message_details("geometry_msgs/msg/TwistStamped")

9. ros2_camera(topic)
   - Kamera goruntusu al (base64)

10. ros2_detect_object(color, plane_z=0.0)
    - Kameradan renk bazli (offline, HSV) nesne tespiti - "kirmizi", "mavi",
      "yesil", "sari" bilinen renkler. Bulunursa base_link cercevesinde
      tahmini {{"x","y","z"}} konumu doner (bkz. ORNEK 4). plane_z, nesnenin
      durdugu yuzeyin yaklasik yuksekligi (masa/zemin, varsayilan 0.0).

10b. ros2_find_object(description)
    - GERCEK, acik-kelime nesne tanima (YOLO-World) - renk degil nesne
      TIPI ("cup", "box", "vacuum cleaner" gibi serbest metin, ingilizce
      terimler daha iyi calisir). Bulunursa {{"x","y","z","graspable"}}
      doner - "graspable":false ise nesne gripper'a gore cok genis,
      tutmaya CALISMA. Gercek derinlik olcumu (Depth Anything V2) kullanir,
      birkac saniye surebilir.

11. ros2_move_arm_to_pose(x, y, z, duration_sec=2.0)
    - Kolun UCUNU (end_effector) base_link cercevesinde (x,y,z) metre
      hedefine goturur (Cartesian - eklem acisi degil). Erisim ~0.35m,
      disina cikan hedefler "status":"error" ile reddedilir.

12. ros2_gripper(position, max_effort=5.0)
    - Gripper ac/kapat: 0.019=tam acik, -0.010=tam kapali/tut.

12b. ros2_navigate_to_location(name) / ros2_save_location(name)
    - Isimli konuma (Nav2 ile otonom) git / mevcut konumu isimle kaydet.
      Sadece SLAM ile haritalanmis bolgelerde calisir - haritalanmamis
      bir yere gitmek istenirse Nav2 guvenli sekilde reddeder.

13. recall_skill(task) / save_skill(task, code)
    - Ogrenilmis beceri cek/kaydet

14. search_docs(query)
    - Yerel ROS2 dokumantasyon ara (ChromaDB RAG)

15. web_search(query)
    - Internet aramasi (yoksa search_docs'a duser)

GUVENLIK: max lineer hiz 0.5 m/s, max acisal hiz 1.0 rad/s{profil_notu}
""".strip()


# -- Test (ROS2 olmadan stub modda) -----------------------------------------
if __name__ == "__main__":
    print("Tool Registry - Stub Modu (ROS2 baglantisi yok)")
    registry = ROS2ToolRegistry()
    print("\n" + "=" * 55)
    print("ARAC MANIFESTOSU:")
    print("=" * 55)
    print(registry.get_tool_manifest())
    print("\n[OK] Tool Registry hazir (WSL2 + rosbridge baslayinca aktif olur)")
