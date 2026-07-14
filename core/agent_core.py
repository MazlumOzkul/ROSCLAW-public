"""
ROSClaw Agent Cekirdegi

Tum bilesenleri birlestiren ana dongu:
Talimat -> Skill kontrolu -> Kod uret -> Validator -> Calistir -> Ogren

AOR (Act-Observe-Rewrite) + VOYAGER skill kutuphanesi
"""

import io, json, re, time, math, threading, contextlib
import requests
from typing import Optional
from dotenv import load_dotenv

from core.validator import SafetyValidator
from core.audit_logger import AuditLogger
from core.model_router import ModelRouter
from memory.skill_library import SkillLibrary
from memory.robot_profiles import RobotProfileStore
from tools.ros2_tools import ROS2ToolRegistry
from core.observation import ObservationNormalizer

# .env dosyasi burada, MERKEZI olarak yuklenir - agent_core hemen hemen her
# yerden import edildigi icin uygulama nasil baslatilirsa baslatilsin
# (gateway, dogrudan script, test) .env bir kere ve guvenilir sekilde okunur.
load_dotenv()


class ToolBlockedError(Exception):
    """Validator bir arac cagrisini BLOCK ettiginde firlatilir."""


class ToolExecutionError(Exception):
    """Arac cagrisi calisti ama basarisiz oldu (orn. ROS2 bagli degil)."""


SYSTEM_PROMPT = """Sen ROSClaw - humanoid robot icin agentic AI sistemisin.
Kullanicilarla hem sohbet edebilir hem de robota fiziksel gorevler
yaptirabilirsin. Gelen her mesaj icin ONCE hangi mod oldugunu kendin karar ver:

MOD A - SOHBET/SORU: Kullanici seninle sohbet ediyor, bir soru soruyor,
selam veriyor, ROS2/robot hakkinda bir seyler soruyor ("nasilsin", "merhaba",
"ne yapabilirsin", "neden TwistStamped kullaniyoruz" gibi). Bu durumda SADECE
DUZ METIN ile, dogal ve kisa bir Turkce cevap yaz. KESINLIKLE kod bloğu
(```) YAZMA - kod bloğu yazarsan sistem bunu robot komutu sanip calistirmaya
calisir, bu yanlis olur.

MOD B - ROBOT KOMUTU: Kullanici robota somut bir fiziksel gorev veriyor
("1 metre ileri git", "sola don", "lazer sensoru oku" gibi). Bu durumda
SADECE calistirilabilir Python kod bloğu yaz, baska aciklama EKLEME.

Kodun calistirilacagi ortamda (MOD B icin) su araclar HAZIR HALDE
tanimlidir - dogrudan cagirabilirsin, import ETMENE gerek YOK (import
ifadeleri calismaz, sandbox bunlari engeller):

{tool_manifest}

Ayrica `time` ve `math` modulleri hazirdir (orn. time.sleep(1.0), math.pi).

KURALLAR:
1. Sadece calistirilabilir Python kodu yaz, yukaridaki araclari dogrudan cagir
2. import ifadeleri KULLANMA - hicbir modulu import edemezsin, sadece verilen araclari kullan
3. Hiz limitleri: lineer max 0.5 m/s, acisal max 1.0 rad/s (bunun disindaki degerler otomatik BLOK edilir)
4. Sadece allowlist'teki topic'leri kullan (/cmd_vel, /gripper/command, /arm/joint_trajectory, /head/cmd)
5. Her hareket icin once sensoru oku, sonra hareket et
6. /cmd_vel icin msg_type MUTLAKA "geometry_msgs/msg/TwistStamped" olmali ve
   hiz degerleri msg["twist"]["linear"/"angular"] altinda olmali (duz Twist
   formati - linear/angular dogrudan en dista - BU KURULUMDA ROBOTU HAREKET ETTIRMEZ)
7. ros2_subscribe(topic) sonucu DOGRUDAN mesaj sozlugudur (orn. odom icin
   veri["pose"]["pose"]["position"]["x"] - nokta/attribute erisimi DEGIL,
   koseli parantezli sozluk erisimi kullan, cunku hepsi Python dict'idir)
8. Basit "X metre ileri/geri git" gorevleri icin karmasik konum hesabi YAPMA,
   sabit hizla belirli sure hareket et (ornek asagida)
9. Hata mesaji gelirse kodu duzelt ve tekrar yaz

ORNEK 1 - "0.5 metre ileri git":
```python
hiz = 0.2
sure = 0.5 / hiz
ros2_publish("/cmd_vel", {"twist": {"linear": {"x": hiz, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}}, "geometry_msgs/msg/TwistStamped")
time.sleep(sure)
ros2_publish("/cmd_vel", {"twist": {"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}}, "geometry_msgs/msg/TwistStamped")
```

ORNEK 2 - "90 derece sola don" (aci->sure: aci_rad / acisal_hiz):
```python
aci_rad = math.pi / 2
acisal_hiz = 0.5
sure = aci_rad / acisal_hiz
ros2_publish("/cmd_vel", {"twist": {"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": acisal_hiz}}}, "geometry_msgs/msg/TwistStamped")
time.sleep(sure)
ros2_publish("/cmd_vel", {"twist": {"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}}, "geometry_msgs/msg/TwistStamped")
```
NOT: `math` modulu de `time` gibi HAZIR HALDE tanimlidir, dogrudan
math.pi / math.sqrt(...) seklinde kullan - "import math" YAZMA, calismaz.

ORNEK 3 - "onde engel var mi kontrol et":
```python
tarama = ros2_subscribe("/scan")
# ONEMLI: LaserScan'deki menzil disi/olcum-yok degerler (inf/NaN) rosbridge'den
# JSON None olarak gelir - "r > 0" filtresinden ONCE "r is not None" kontrolu
# YAPILMAZSA TypeError firlar. Asagidaki gibi tek satirda ikisini de kontrol et.
mesafeler = [r for r in tarama["ranges"] if r is not None and r > 0]
if mesafeler and min(mesafeler) < 0.5:
    print("Engel var:", min(mesafeler), "metre")
else:
    print("Yol acik")
```

ORNEK 4 - "kirmizi topu al" (kol+gripper+kamera ile nesne tutma):
```python
nesne = ros2_detect_object("kirmizi")
if not nesne["found"]:
    print("Nesne bulunamadi:", nesne.get("reason"))
else:
    ros2_gripper(0.019)  # once gripper'i ac
    ros2_move_arm_to_pose(nesne["x"], nesne["y"], nesne["z"] + 0.06)  # yaklas
    ros2_move_arm_to_pose(nesne["x"], nesne["y"], nesne["z"] + 0.015)  # in
    ros2_gripper(-0.010)  # tut
    ros2_move_arm_to_pose(0.15, 0.0, 0.2)  # kaldir
```
NOT: ros2_move_arm_to_pose(x,y,z) kolun UCUNU (end_effector) base_link
cercevesindeki metre cinsinden (x,y,z) konumuna goturur - eklem acisi
DEGIL, dogrudan hedef nokta verilir (IK kendi icinde cozulur). Kolun
gercek erisimi ~0.35m - cok uzak/cok alcak/cok yuksek hedefler
ros2_move_arm_to_pose'un dondurdugu "status":"error" ile reddedilir,
boyle bir durumda hatayi print'le ve dur, tekrar deneme.
ros2_detect_object bilinen renkler: kirmizi/red, mavi/blue, yesil/green,
sari/yellow. Bulunamazsa "found": false doner, o durumda islem yapma.

ORNEK 5 - "bardagi al" (renk DEGIL, nesne TIPIYLE tanima - YOLO-World):
```python
nesne = ros2_find_object("cup")  # Turkce yerine Ingilizce terim daha iyi calisir
if not nesne["found"]:
    print("Nesne bulunamadi:", nesne.get("reason"))
elif not nesne["graspable"]:
    print("Nesne bulundu ama tutulamiyor:", nesne.get("reason"))
else:
    ros2_gripper(0.019)
    ros2_move_arm_to_pose(nesne["x"], nesne["y"], nesne["z"] + 0.06)
    ros2_move_arm_to_pose(nesne["x"], nesne["y"], nesne["z"] + 0.015)
    ros2_gripper(-0.010)
    ros2_move_arm_to_pose(0.15, 0.0, 0.2)
```
NOT: ros2_find_object, ros2_detect_object'ten (sadece renk) FARKLI - GERCEK
nesne tipini (kupa, kutu, supurge, ...) taniyabiliyor (YOLO-World, acik-
kelime). Ama sonuc "graspable": false donebilir - gripper'in fiziksel
acikligina sigmayan (cok genis) nesneler icin bunu ZORLA tutmaya CALISMA,
kullaniciya bildir ve dur.

NOT (SADECE gorsel girdi ekliyse - Claude): Talimat nesneyi ISIMLENDIRMIYORSA
("gordugun nesneyi kavra", "onundeki seyi al" gibi), ekteki kamera goruntusune
BAK ve gordugun nesneyi kisa, somut bir Ingilizce terimle (orn. "red apple",
"blue cup") tanimla, sonra bu terimi ros2_find_object'e description olarak
ver - ros2_detect_object/ros2_find_object KENDISI goruntuyu gormez, sadece
SENIN verdigin metinle arama yapar.

ORNEK 6 - "mutfaga git" (isimli konuma Nav2 ile otonom navigasyon):
```python
sonuc = ros2_navigate_to_location("mutfak")
if sonuc["status"] != "ok":
    print("Gidilemedi:", sonuc.get("reason"))
else:
    print("Vardim.")
```
NOT: Konum onceden "burasi mutfak" tarzi bir komutla ros2_save_location("mutfak")
ile kaydedilmis olmali - kayitli olmayan bir isim verilirse hata doner.
Nav2 SADECE haritalanmis (SLAM ile kesfedilmis) bolgelerde calisir; hedef
haritalanmamis bir alandaysa GUVENLI SEKILDE reddeder (rastgele yon
denemez) - bu durumda kullaniciya bildirip DUR, tekrar deneme.

ORNEK 7 - "burasi mutfak, kaydet" (mevcut konumu isimlendirme):
```python
sonuc = ros2_save_location("mutfak")
print("Kaydedildi:" if sonuc["status"]=="ok" else "Hata:", sonuc)
```

ORNEK 8 - "merhaba, nasilsin?" (SOHBET modu - kod bloğu YOK, sadece metin):
Merhaba! Iyiyim, tesekkurler. Robotu kontrol etmeye hazirim - bir gorev verebilir
ya da ROS2/robot hakkinda soru sorabilirsin.

CIKTI FORMATI:
- MOD B (robot komutu) icin: sadece Python kod bloğu, baska aciklama ekleme.
  ```python
  # kodun buraya
  ```
- MOD A (sohbet) icin: sadece duz metin, KOD BLOĞU YOK.
"""


class AgentCore:
    def __init__(self,
                 ollama_url: str = None,
                 model: str = "qwen2.5-coder:7b",
                 ros_host: str = None,
                 ros_port: int = None):
        import os
        self.ollama_url = ollama_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = model
        self.router = ModelRouter()
        self.validator = SafetyValidator()
        self.audit_logger = AuditLogger()
        self.skill_lib = SkillLibrary()
        # Bilesik gorevlerin (orn. "kirmiziyi birak ve maviyi al") alt-adimlara
        # nasil bolundugunu ayri bir dosyada saklar - SkillLibrary'nin ayni
        # embedding+kategori-guard mekanizmasini yeniden kullanir, "code"
        # alaninda JSON-kodlanmis adim listesi tutar.
        self.plan_cache = SkillLibrary(path="skills/task_plans.json")
        self.profile_store = RobotProfileStore()
        self.normalizer = ObservationNormalizer()
        self.run_log = []
        self.active_profile = None

        if ros_host or ros_port:
            # Acikca adres verilmisse (orn. testlerde) profil sistemini atla
            self.tools = ROS2ToolRegistry(ros_host or "localhost", ros_port or 9090)
        else:
            active = self.profile_store.get_active()
            if active:
                self.tools = ROS2ToolRegistry(active["host"], active["port"])
                self.active_profile = active
                self.validator.apply_profile_overrides(
                    velocity_limits=active.get("velocity_limits"),
                    topic_allowlist=active.get("topic_allowlist"))
            else:
                # Hic profil yoksa .env'deki degerlere dus (geriye uyumluluk)
                self.tools = ROS2ToolRegistry(
                    os.environ.get("ROS2_HOST", "localhost"),
                    int(os.environ.get("ROS2_PORT", "9090")))
        self._wire_reflex()

    def _wire_reflex(self):
        """/scan verisi her geldiginde _on_reflex_trigger'i cagiracak sekilde
        baglar - bkz. tools/ros2_tools.py _on_scan_message."""
        self.tools.reflex_callback = self._on_reflex_trigger

    def _on_reflex_trigger(self, front_distance: float):
        """
        "Cerebellum" refleksi - /scan verisi geldikce roslibpy'nin KENDI
        callback thread'inde, LLM dongusunden TAMAMEN BAGIMSIZ olarak
        cagirilir. Engel kritik esigin (lidar_emergency_stop_distance)
        altina dusunce, LLM'in bir sonraki kod uretme dongusunu (saniyeler
        surebilir) beklemeden ANINDA e-stop tetiklenir. "Brain" (LLM, yavas,
        ~saniyeler) ile "Cerebellum" (sensor-tetiklemeli refleks, anlik)
        ayriminin temeli budur.
        """
        threshold = self.validator.config.get("safety_zones", {}).get("lidar_emergency_stop_distance")
        if threshold is None or front_distance >= threshold or self.validator._estop_active:
            return
        self.validator.emergency_stop()
        print(f"\n[REFLEKS] Kritik yakinlik ({front_distance:.2f}m < {threshold}m) - "
              f"LLM beklenmeden E-STOP tetiklendi!\n")
        self.audit_logger.log(
            {"front_distance": front_distance}, "reflex_estop", {},
            "BLOCK", f"Refleks: onde {front_distance:.2f}m < acil esik {threshold}m", outcome=None)

    def switch_robot(self, profile_id: str) -> dict:
        """
        Calisirken baska bir robota gec - WiFi'de baska bir aga baglanmak
        gibi. Mevcut baglantiyi keser, yeni profilin adresine baglanir,
        guvenlik limitlerini/izinli topic listesini o profile gore gunceller.
        """
        profile = self.profile_store.get(profile_id)
        if not profile:
            return {"status": "error", "reason": "Profil bulunamadi"}

        try:
            self.tools.disconnect()
        except Exception:
            pass

        self.tools = ROS2ToolRegistry(profile["host"], profile["port"])
        connected = self.tools.connect()
        self._wire_reflex()

        self.validator.apply_profile_overrides(
            velocity_limits=profile.get("velocity_limits"),
            topic_allowlist=profile.get("topic_allowlist"))

        self.active_profile = profile
        self.profile_store.set_active(profile["id"])

        return {"status": "ok" if connected else "error",
                "connected": connected, "profile": profile}

    # Bilesik/coklu-adim talimatlarda gecen tipik baglaclar - bunlardan biri
    # varsa gorev planlayiciyi (LLM ile kesin bolme) devreye sokariz. Sade
    # tek-eylemli talimatlarda (buyuk cogunluk) bu ek LLM cagrisini atlayip
    # dogrudan _run_single'a gideriz - gereksiz gecikme eklememek icin.
    _COMPOUND_HINTS = [" ve ", " sonra ", " ardindan ", " ardından ", ", ",
                        "once ", "önce ", "ilk once", "ilk önce"]

    def _looks_compound(self, instruction: str) -> bool:
        text = f" {instruction.lower()} "
        return any(hint in text for hint in self._COMPOUND_HINTS)

    def _decompose(self, instruction: str) -> list:
        """
        Talimati atomik alt-gorevlere ayirir. Once plan hafizasina (plan_cache)
        bakar - ayni/benzer bilesik talimat daha once bolunduyse LLM'e
        gitmeden dogrudan o plani kullanir. Bulunamazsa Qwen'e sorup sonucu
        gelecekte tekrar kullanmak icin kaydeder. Herhangi bir sorunda
        (yaniti parse edememe, LLM hatasi) GUVENLI GERI DONUS: talimati
        TEK adimli bir plan olarak dondurur (_run_single yolunu bozmaz).
        """
        cached_plan = self.plan_cache.recall(instruction)
        if cached_plan:
            try:
                steps = json.loads(cached_plan["code"])
                if isinstance(steps, list) and steps:
                    print(f"[PLAN-CACHE] Plan hafizadan bulundu ({len(steps)} adim)")
                    return steps
            except Exception:
                pass

        system = ("Sen bir gorev ayristirma asistanisin. Kullanicidan gelen "
                   "talimati incele:\n\n"
                   "- Talimat SOHBET ise (soru, selam, teknik soru vb.) veya "
                   "TEK, BOLUNEMEZ bir robot eylemi ise: sadece tek bir "
                   "satirda, talimati OLDUGU GIBI (degistirmeden) geri yaz.\n"
                   "- Talimat BIRDEN FAZLA AYRI eylem iceriyorsa (orn. "
                   "\"X yap VE Y yap\", \"once X sonra Y\"): her eylemi AYRI "
                   "bir satirda, numarali liste olarak yaz. Her satir KENDI "
                   "BASINA anlasilir, tam bir talimat olmali.\n\n"
                   "Sadece numarali listeyi (ya da tek satiri) yaz, baska "
                   "aciklama ekleme.")
        raw = self._call_ollama([{"role": "user", "content": instruction}],
                                 system, temperature=0.1)
        if not raw:
            return [instruction]

        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        steps = []
        for ln in lines:
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", ln).strip()
            if cleaned:
                steps.append(cleaned)
        if not steps:
            return [instruction]

        if len(steps) > 1:
            self.plan_cache.save(instruction, json.dumps(steps, ensure_ascii=False))
        return steps

    def run(self, instruction: str) -> dict:
        """
        Ana giris noktasi. Talimat bilesik/coklu-adimli GORUNUYORSA
        (baglac sezgiseline gore), once atomik alt-gorevlere boler ve
        her birini AYRI AYRI _run_single ile calistirir - her adim kendi
        guvenlik dogrulamasindan, hafiza kontrolunden ve yeniden deneme
        dongusunden gecer. Tek bir buyuk kod blogunun butun coklu-adim
        mantigini hatasiz uretmesini beklemekten cok daha guvenilir
        (orn. "X'i birak ve Y'yi al" gibi bilesik komutlarda daha once
        gordugumuz mantik hatalarini onler).
        """
        if not self._looks_compound(instruction):
            return self._run_single(instruction)

        start = time.time()
        print(f"\n{'='*55}")
        print(f"BILESIK GOREV: {instruction}")
        print(f"{'='*55}")
        steps = self._decompose(instruction)

        if len(steps) <= 1:
            # Sezgisel "bilesik gorunuyor" dedi ama planlayici tek adim
            # dondurdu (orn. "X ve Y" aslinda tek bir isim/ifadeydi) -
            # normal tek-adim yoluna don.
            return self._run_single(instruction)

        print(f"[PLAN] {len(steps)} adima bolundu: {steps}")
        step_results = []
        for i, step in enumerate(steps):
            print(f"\n--- ADIM {i+1}/{len(steps)}: {step} ---")
            result = self._run_single(step)
            step_results.append({"step": i+1, "instruction": step, **result})
            if result["status"] not in ("success", "chat"):
                return {
                    "status": "partial_failure",
                    "instruction": instruction,
                    "plan": steps,
                    "steps": step_results,
                    "completed_steps": i,
                    "total_steps": len(steps),
                    "elapsed": time.time()-start,
                }

        return {
            "status": "success",
            "instruction": instruction,
            "plan": steps,
            "steps": step_results,
            "total_steps": len(steps),
            "elapsed": time.time()-start,
        }

    def _run_single(self, instruction: str) -> dict:
        """Tek, atomik bir talimati calistirir (AOR dongusu). `run()` bilesik
        talimatlari bu metodu birden fazla kez cagirarak yerine getirir."""
        print(f"\n{'='*55}")
        print(f"GOREV: {instruction}")
        print(f"{'='*55}")
        start = time.time()

        # 1. Skill kutuphanesine bak
        cached = self.skill_lib.recall(instruction)
        if cached:
            print(f"[CACHE] Hafizadan bulundu (benzerlik: {cached['similarity']})")
            result = self._execute_code(cached["code"])
            if result["success"]:
                self.skill_lib.save(instruction, cached["code"])
                return {"status": "success", "source": "cache",
                        "code": cached["code"], "elapsed": time.time()-start}

        # 2. Ollama'ya sor - model kendisi sohbet mi robot komutu mu karar verir
        print("[GEN] Yanit degerlendiriliyor (Qwen2.5-Coder)...")
        user_content = instruction

        # Robotun hareket formati bilinmiyorsa (movement_style="unknown"),
        # kesfi modelin "yapar mi yapmaz mi" secimine birakmiyoruz - kucuk
        # yerel modeller talimata ragmen kendi onceden bildigi (orn. duz
        # Twist) formati tahmin etmeyi tercih edebiliyor. Bunun yerine
        # topic+tip bilgisini KOD SEVIYESINDE, deterministik olarak once
        # kendimiz cekip mesaja ekliyoruz - boylece dogru bilgi garanti
        # modelin onunde oluyor, bir "arac cagirma karari"na bagli kalmiyor.
        if (self.active_profile or {}).get("movement_style") == "unknown":
            discovery = self.tools.ros2_topics_with_types()
            if discovery.get("status") == "ok":
                user_content = (
                    f"{instruction}\n\n"
                    f"[Sistem notu - bu robotun mevcut topic'leri ve GERCEK mesaj "
                    f"tipleri (tahmin etme, bunlari kullan): {discovery['topics']}. "
                    f"Detayli alan yapisi icin ros2_message_details(mesaj_tipi) "
                    f"cagirabilirsin.]"
                )

        messages = [{"role": "user", "content": user_content}]
        system = SYSTEM_PROMPT.replace(
            "{tool_manifest}", self.tools.get_tool_manifest(profile=self.active_profile))

        # Yonlendirme: talimat SYSTEM_PROMPT'taki bilinen hicbir ORNEK kaliba
        # benzemiyorsa (novelty) VEYA kelime-bazli karmasiklik esigi asiliyorsa
        # VE internet varsa, Claude API denenir - kisa/basit GORUNEN ama
        # Qwen'in hic ornegini gormedigi talimatlar (orn. "kolunu kaldir ve
        # salla") bu sayede kelime sayisindan bagimsiz olarak daha guclu
        # modele kayar. Claude basarisiz olursa (API anahtari yok, internet
        # kesildi, cagri hata verdi) sessizce Qwen'e dusulur.
        threshold = self.router.config["routing"]["complexity_threshold"]
        novel = self.router._novelty_score(instruction) > 0.0
        complex_enough = self.router._complexity_score(instruction) >= threshold
        use_claude = (novel or complex_enough) and self.router._internet_available()
        camera_image_b64 = None
        # Talimat, nesneyi ISIMLENDIRMEDEN gorsel olarak isaret ediyor mu
        # ("gordugun nesneyi kavra", "grasp the object you see" gibi)?
        # Bunu bir anahtar-kelime listesiyle DEGIL (bu SADECE Turkce'de
        # calisirdi - test edildi: "grasp the object you see" ayni riski
        # tasiyor ama Turkce liste bunu yakalayamiyordu, Qwen "kirmizi"
        # diye UYDURUP kodu calistirdi) kucuk, dil-bagimsiz bir LLM
        # siniflandirma sorusuyla cozuyoruz.
        vague_object_ref = self._references_unnamed_object(instruction)
        if use_claude:
            reason = "bilinmeyen gorev kalibi" if novel else "yuksek karmasiklik"
            print(f"  [ROUTE] Claude API denenecek ({reason})")
            # Claude gorsel girdi kabul edebiliyor - Qwen2.5-Coder edemiyor.
            # Bu sayede "gordugun nesneyi kavra" gibi ISIM VERILMEYEN
            # talimatlarda Claude kameraya gercekten bakip somut bir nesne
            # adi (orn. "kirmizi elma") uretebilir - metin-bazli yonlendirme
            # tek basina bunu cozemezdi. Gorsel, ilgisiz gorevlerde de
            # (orn. "kolunu kaldir ve salla") zararsiz ekstra baglam olarak
            # eklenir - sadece vague_object_ref durumunda Qwen fallback'i
            # ASAGIDA ayrica engellenir.
            camera_image_b64 = self._get_camera_jpeg_b64()
            if camera_image_b64:
                print("  [ROUTE] Kamera karesi Claude'a eklendi (gorsel baglam)")

        previous_codes = []
        for attempt in range(5):
            print(f"\n  Deneme {attempt+1}/5")

            # Sicaklik (temperature) her denemede biraz artar - deneme 1'de
            # deterministik/tutarli kod, sonraki denemelerde model ayni hatayi
            # tekrarlamak yerine farkli bir yaklasim denesin diye cesitlilik
            # artirilir. temp 0.1 sabit kalsaydi kucuk model genelde ayni
            # (hatali) kodu tekrar tekrar uretiyordu.
            temperature = min(0.1 + attempt * 0.2, 0.9)

            raw = None
            if use_claude:
                raw = self._call_claude(messages, system, temperature=temperature,
                                         image_b64=camera_image_b64)
                if not raw:
                    if vague_object_ref:
                        # Bu gorev GORSEL BAGLAM gerektirdigi icin Claude'a
                        # yonlendirilmisti (orn. "gordugun nesneyi kavra") -
                        # Qwen2.5-Coder'in kamerasi YOK, bu goreve dusmesine
                        # izin verirsek sahneyi gormeden "goruyorum" gibi bir
                        # sey uydurabilir (test edildi, gercekten oluyor).
                        # Qwen'e dusmek yerine durustce bildir ve dur.
                        print("  [FAIL] Claude basarisiz - bu gorev gorsel baglam "
                              "gerektiriyordu, Qwen'e (kamerasiz) DUSULMUYOR")
                        self._log(instruction, "", "failed", attempt+1)
                        return {"status": "error", "instruction": instruction,
                                "reason": "Bu talimat nesneyi isimlendirmiyor, "
                                          "kamera goruntusune bakarak karar vermek "
                                          "icin Claude API gerekiyor ama su an "
                                          "kullanilamiyor (kredi/baglanti sorunu "
                                          "olabilir). Lutfen nesnenin adini acikca "
                                          "belirt (orn. 'kirmizi elmayi kavra').",
                                "elapsed": time.time()-start}
                    print("  [FALLBACK] Claude basarisiz/mevcut degil, Qwen'e dusuluyor")
                    use_claude = False  # bu ve sonraki denemelerde tekrar deneme

            if not raw:
                raw = self._call_ollama(messages, system, temperature=temperature)
            if not raw:
                print("  [ERR] Modelden yanit alinamadi")
                continue

            code = self._extract_code(raw)

            if code is None:
                # Kod bloğu yok -> bu bir SOHBET yaniti, robot komutu degil.
                # Hicbir arac cagrilmadi, hicbir seyi calistirmiyoruz.
                print(f"  [CHAT] Sohbet yaniti: {raw[:100]}")
                self._log(instruction, "", "chat", attempt+1)
                return {"status": "chat", "reply": raw.strip(),
                        "elapsed": time.time()-start}

            if not self._is_meaningful_code(code):
                print(f"  [ERR] Bos/placeholder kod: {code!r}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user",
                                  "content": "Bu gecerli, calistirilabilir bir kod degil (bos veya sadece "
                                              "yorum satiri). Gercekten gorevi yerine getiren, arac "
                                              "cagrilari iceren calistirilabilir Python kodu yaz."})
                continue

            if code in previous_codes:
                print(f"  [TEKRAR] Ayni kod tekrar uretildi, farkli yaklasim istenecek")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user",
                                  "content": "Bu kodu daha once denedin ve basarisiz oldu, AYNISINI tekrar "
                                              "yazdin. Tamamen FARKLI bir yaklasim dene (orn. farkli bir "
                                              "arac kullan, veri erisim seklini degistir, daha basit bir "
                                              "yontem sec)."})
                continue
            previous_codes.append(code)

            print(f"  Uretilen kod (sicaklik={temperature:.1f}):\n{'-'*40}")
            print(code[:200] + ("..." if len(code) > 200 else ""))
            print("-"*40)

            val_result = self._validate_code(code)
            if not val_result["safe"]:
                print(f"  [BLOCK] Validator: {val_result['reason']}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user",
                                  "content": f"Guvenlik hatasi: {val_result['reason']}. Kodu duzelt."})
                continue

            result = self._execute_code(code)
            if result["success"]:
                print(f"  [OK] Basarili!")
                self.skill_lib.save(instruction, code)
                self._log(instruction, code, "success", attempt+1)
                return {"status": "success", "source": "generated",
                        "code": code, "attempts": attempt+1,
                        "elapsed": time.time()-start}

            error = result.get("error", "Bilinmeyen hata")
            print(f"  [FAIL] Calisma hatasi: {error[:100]}")
            messages.append({"role": "assistant", "content": code})
            messages.append({"role": "user",
                              "content": f"Hata olustu:\n{error}\nKodu duzelt. Ayni hatayi tekrarlama, "
                                          "once neyin yanlis gittigini dusun, farkli bir yol dene."})

        self._log(instruction, "", "failed", 5)
        return {"status": "failed", "instruction": instruction,
                "elapsed": time.time()-start}

    def _call_ollama(self, messages: list, system: str, temperature: float = 0.1) -> Optional[str]:
        """Ollama'dan ham yaniti al (sohbet metni veya kod bloğu icerebilir)."""
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}] + messages,
                "stream": False,
                "options": {"temperature": temperature, "num_ctx": 4096}
            }
            r = requests.post(f"{self.ollama_url}/api/chat",
                              json=payload, timeout=60)
            return r.json()["message"]["content"]
        except Exception as e:
            print(f"  Ollama hatasi: {e}")
            return None

    def _call_claude(self, messages: list, system: str, temperature: float = 0.1,
                      image_b64: Optional[str] = None) -> Optional[str]:
        """Claude API'den ham yanit al - _call_ollama ile AYNI sekil (ayni
        SYSTEM_PROMPT/arac manifesti, ayni cok-turlu mesaj listesi) boylece
        retry dongusu hangi modelin cevap verdiginden bagimsiz calisir.

        image_b64 verilirse (JPEG, base64) ilk kullanici mesajina gorsel
        blok olarak eklenir - `messages` listesinin kendisi DEGISTIRILMEZ
        (bu liste Ollama fallback'i ile de paylasiliyor, Ollama/qwen2.5-coder
        gorsel giris kabul etmiyor)."""
        import os
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key or api_key == "your_claude_api_key_here":
                return None
            client = anthropic.Anthropic(api_key=api_key)

            send_messages = messages
            if image_b64 and messages and messages[0]["role"] == "user" \
                    and isinstance(messages[0]["content"], str):
                send_messages = [dict(m) for m in messages]
                send_messages[0] = {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg",
                            "data": image_b64}},
                        {"type": "text", "text": messages[0]["content"]},
                    ],
                }

            response = client.messages.create(
                model=self.router.config["models"]["frontier"]["model"],
                max_tokens=2048,
                temperature=temperature,
                system=system,
                messages=send_messages,
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            return text or None
        except Exception as e:
            print(f"  Claude API hatasi: {e}")
            return None

    def _references_unnamed_object(self, instruction: str) -> bool:
        """Talimat, ne oldugu soylenmeyen/isimlendirilmeyen bir fiziksel
        nesneye atifta bulunuyor mu ("gordugun nesneyi kavra", "grasp the
        object you see" gibi)? Anahtar-kelime listesi YERINE kucuk bir
        siniflandirma sorusu kullanilir - boylece talimatin dili (Turkce,
        Ingilizce, baska herhangi biri) onemli olmadan calisir; sabit bir
        kelime listesi HER ZAMAN sadece test edilen dile ozel kalirdi."""
        system = ("Asagidaki talimat, ne oldugu SOYLENMEYEN/ISIMLENDIRILMEYEN "
                   "bir fiziksel nesneye atifta bulunuyor mu (orn. 'gordugun "
                   "nesneyi kavra', 'onundeki seyi al', 'grasp the object you "
                   "see', 'pick up what is in front of you')? Talimat hangi "
                   "dilde olursa olsun cevapla. SADECE 'EVET' ya da 'HAYIR' "
                   "yaz, baska hicbir sey yazma.")
        raw = self._call_ollama([{"role": "user", "content": instruction}],
                                 system, temperature=0.0)
        return bool(raw) and "evet" in raw.strip().lower()[:20]

    def _get_camera_jpeg_b64(self) -> Optional[str]:
        """Kameradan bir kare alip JPEG+base64'e cevirir (Claude'un gorsel
        girdisi icin standart bir resim formati bekler - ros2_camera ise
        ROS'un ham/sikistirilmamis piksel formatini donduruyor, once
        decode_ros_image ile numpy diziye, sonra JPEG'e cevrilmesi gerekiyor).
        Kamera yoksa/hata olursa sessizce None doner - Claude metin-bazli
        (gorsel olmadan) devam eder."""
        try:
            result = self.tools.ros2_camera()
            if result.get("status") != "ok":
                return None
            import cv2, base64
            from tools.object_detection import decode_ros_image
            image_bgr = decode_ros_image(result["data"])
            ok, buf = cv2.imencode(".jpg", image_bgr)
            if not ok:
                return None
            return base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception as e:
            print(f"  [WARN] Kamera karesi hazirlanamadi: {e}")
            return None

    def _is_meaningful_code(self, code: str) -> bool:
        """
        Yorum satirlari ve bos satirlar cikarildiktan sonra gercekten
        calistirilabilir bir ifade kalmis mi? Kucuk/quantize modeller bazen
        "# kodun buraya" gibi sablonu aynen geri kopyalayabiliyor - bu tur
        no-op'lar hicbir sey yapmadan "basarili" sayilmasin diye reddedilir.
        """
        lines = [ln.strip() for ln in code.splitlines()]
        real_lines = [ln for ln in lines if ln and not ln.startswith("#")]
        if not real_lines:
            return False
        if all(ln in ("pass", "...") for ln in real_lines):
            return False
        return True

    # Kod bloğu isaretlemeyi unutan modeller icin guvenlik agi: bu isim-
    # lerden biri metinde `isim(` seklinde geciyorsa VE metin gecerli Python
    # olarak derleniyorsa, bu SOHBET degil unutulmus bir kod bloğudur.
    _TOOL_NAMES = ("ros2_publish", "ros2_subscribe", "ros2_service", "ros2_action",
                   "ros2_get_param", "ros2_set_param", "ros2_list_topics",
                   "ros2_camera", "ros2_detect_object", "ros2_find_object",
                   "ros2_move_arm_to_pose", "ros2_gripper",
                   "ros2_navigate_to_location", "ros2_save_location",
                   "recall_skill", "save_skill", "search_docs", "web_search")

    def _extract_code(self, text: str) -> Optional[str]:
        """
        Model ciktisindan Python kodunu cikar. Once ``` kod bloğu aranir.
        Bulunamazsa, metin gercek Python olarak derleniyor VE bilinen bir
        arac fonksiyonunu cagiriyorsa yine kod olarak kabul edilir (model
        bazen kod bloğu isaretlemeyi unutabiliyor - salt "kod bloğu yok"
        kuralina korlemesine guvenmek boyle durumlarda komutu sessizce
        sohbete cevirip robotu hic calistirmaz, bu daha buyuk bir risktir).
        Ikisi de yoksa None doner - bu durum SOHBET modu olarak yorumlanir.
        """
        match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        stripped = text.strip()
        if any(f"{name}(" in stripped for name in self._TOOL_NAMES):
            try:
                compile(stripped, "<candidate>", "exec")
                return stripped
            except SyntaxError:
                pass
        return None

    def _validate_code(self, code: str) -> dict:
        """Uretilen kodda guvenlik acigi var mi? Hizli on-kontrol (import zaten
        sandbox'ta calismaz, ama net bir hata mesaji icin erken yakalariz)."""
        dangerous = ["os.system", "subprocess", "eval(",
                     "exec(", "rm -rf", "__import__", "import "]
        for keyword in dangerous:
            if keyword in code:
                return {"safe": False,
                        "reason": f"Tehlikeli/desteklenmeyen ifade: {keyword.strip()}"}
        return {"safe": True, "reason": "Guvenli"}

    def _make_tool_namespace(self, call_log: list) -> dict:
        """
        Uretilen kodun calisacagi kisitli isim uzayi.
        Her arac cagrisi ONCE SafetyValidator'dan gecer - BLOCK ise
        ToolBlockedError firlatilir ve kod calismayi durdurur. Her cagri
        (ALLOW veya BLOCK, basarili ya da hatali) audit_logger'a l_t =
        (t, o_t, u_t, d_t, r_t, y_t) formatinda kalici olarak yazilir
        (bkz. core/audit_logger.py, arXiv 2603.26997 formulasyonu).
        """
        def _snapshot_observation() -> dict:
            front = None
            try:
                front = self.tools.get_front_distance()
            except Exception:
                pass
            return {"front_distance": front, "estop": self.validator._estop_active}

        def _check(tool_name: str, tool_args: dict) -> dict:
            # ros2_publish icin en son lazer verisinden hesaplanan on mesafe
            # validator'a enjekte edilir - LiDAR yakinlik korumasi (bkz.
            # validator.py _validate_publish) bunu gormeden calisamaz.
            if tool_name == "ros2_publish":
                tool_args = dict(tool_args)
                tool_args["front_distance"] = None
                try:
                    tool_args["front_distance"] = self.tools.get_front_distance()
                except Exception:
                    pass

            observation = _snapshot_observation()
            result = self.validator.validate(tool_name, tool_args)
            call_log.append({"tool": tool_name, "decision": result.decision,
                              "reason": result.reason})
            if result.decision == "BLOCK":
                self.audit_logger.log(observation, tool_name, tool_args,
                                       "BLOCK", result.reason, outcome=None)
                raise ToolBlockedError(f"{tool_name} engellendi: {result.reason}")
            return {"observation": observation, "tool_args": tool_args, "reason": result.reason}

        def _unwrap(tool_name: str, result, ctx: dict):
            outcome = "error" if isinstance(result, dict) and result.get("status") == "error" else "success"
            self.audit_logger.log(ctx["observation"], tool_name, ctx["tool_args"],
                                   "ALLOW", ctx["reason"], outcome=outcome)
            if outcome == "error":
                raise ToolExecutionError(f"{tool_name} hatasi: {result.get('reason')}")
            return result

        def ros2_publish(topic, msg, msg_type="geometry_msgs/Twist"):
            ctx = _check("ros2_publish", {"topic": topic, "msg": msg})
            return _unwrap("ros2_publish", self.tools.ros2_publish(topic, msg, msg_type), ctx)

        def ros2_subscribe(topic, timeout=3.0):
            ctx = _check("ros2_subscribe", {"topic": topic})
            result = _unwrap("ros2_subscribe", self.tools.ros2_subscribe(topic, timeout), ctx)
            # Cagiran koda sarmalayici zarf (status/topic) yerine dogrudan
            # mesaj icerigini ver - orn. odom["pose"]["pose"]["position"]["x"]
            return result.get("data") if isinstance(result, dict) else result

        def ros2_service(service, request=None, service_type="std_srvs/Trigger"):
            ctx = _check("ros2_service", {"service": service})
            return _unwrap("ros2_service", self.tools.ros2_service(service, request, service_type), ctx)

        def ros2_action(action, goal):
            ctx = _check("ros2_action", {"action": action, "goal": goal})
            return _unwrap("ros2_action", self.tools.ros2_action(action, goal), ctx)

        def ros2_get_param(node, param):
            ctx = _check("ros2_get_param", {"node": node, "param": param})
            return _unwrap("ros2_get_param", self.tools.ros2_get_param(node, param), ctx)

        def ros2_set_param(node, param, value):
            ctx = _check("ros2_set_param", {"node": node, "param": param, "value": value})
            return _unwrap("ros2_set_param", self.tools.ros2_set_param(node, param, value), ctx)

        def ros2_list_topics():
            ctx = _check("ros2_list_topics", {})
            return _unwrap("ros2_list_topics", self.tools.ros2_list_topics(), ctx)

        def ros2_topics_with_types():
            ctx = _check("ros2_topics_with_types", {})
            return _unwrap("ros2_topics_with_types", self.tools.ros2_topics_with_types(), ctx)

        def ros2_message_details(message_type):
            ctx = _check("ros2_message_details", {"message_type": message_type})
            return _unwrap("ros2_message_details", self.tools.ros2_message_details(message_type), ctx)

        def ros2_camera(topic="/camera/image_raw"):
            ctx = _check("ros2_camera", {"topic": topic})
            return _unwrap("ros2_camera", self.tools.ros2_camera(topic), ctx)

        def ros2_detect_object(color, plane_z=0.0):
            ctx = _check("ros2_detect_object", {"color": color, "plane_z": plane_z})
            return _unwrap("ros2_detect_object",
                            self.tools.ros2_detect_object(color, plane_z), ctx)

        def ros2_find_object(description):
            ctx = _check("ros2_find_object", {"description": description})
            return _unwrap("ros2_find_object",
                            self.tools.ros2_find_object(description), ctx)

        def ros2_move_arm_to_pose(x, y, z, duration_sec=2.0):
            ctx = _check("ros2_move_arm_to_pose", {"x": x, "y": y, "z": z})
            return _unwrap("ros2_move_arm_to_pose",
                           self.tools.ros2_move_arm_to_pose(x, y, z, duration_sec), ctx)

        def ros2_gripper(position, max_effort=5.0):
            ctx = _check("ros2_gripper", {"position": position, "max_effort": max_effort})
            return _unwrap("ros2_gripper",
                            self.tools.ros2_gripper(position, max_effort), ctx)

        def ros2_navigate_to_location(name, timeout=90.0):
            ctx = _check("ros2_navigate_to_location", {"name": name})
            return _unwrap("ros2_navigate_to_location",
                            self.tools.ros2_navigate_to_location(name, timeout), ctx)

        def ros2_save_location(name):
            ctx = _check("ros2_save_location", {"name": name})
            return _unwrap("ros2_save_location", self.tools.ros2_save_location(name), ctx)

        def recall_skill(task):
            ctx = _check("recall_skill", {"task": task})
            return _unwrap("recall_skill", self.skill_lib.recall(task), ctx)

        def save_skill(task, code):
            ctx = _check("save_skill", {"task": task})
            return _unwrap("save_skill", self.skill_lib.save(task, code), ctx)

        def search_docs(query):
            ctx = _check("search_docs", {"query": query})
            from tools.search_docs import search_docs as _search_docs
            return _unwrap("search_docs", _search_docs(query), ctx)

        def web_search(query):
            ctx = _check("web_search", {"query": query})
            from tools.web_tools import web_search as _web_search
            return _unwrap("web_search", _web_search(query), ctx)

        safe_builtins = {
            "print": print, "range": range, "len": len, "abs": abs,
            "min": min, "max": max, "float": float, "int": int, "str": str,
            "bool": bool, "dict": dict, "list": list, "tuple": tuple,
            "enumerate": enumerate, "zip": zip, "round": round, "sorted": sorted,
            "True": True, "False": False, "None": None, "Exception": Exception,
        }

        return {
            "__builtins__": safe_builtins,
            "time": time,
            "math": math,
            "ros2_publish": ros2_publish,
            "ros2_subscribe": ros2_subscribe,
            "ros2_service": ros2_service,
            "ros2_action": ros2_action,
            "ros2_get_param": ros2_get_param,
            "ros2_set_param": ros2_set_param,
            "ros2_list_topics": ros2_list_topics,
            "ros2_topics_with_types": ros2_topics_with_types,
            "ros2_message_details": ros2_message_details,
            "ros2_camera": ros2_camera,
            "ros2_detect_object": ros2_detect_object,
            "ros2_find_object": ros2_find_object,
            "ros2_move_arm_to_pose": ros2_move_arm_to_pose,
            "ros2_gripper": ros2_gripper,
            "ros2_navigate_to_location": ros2_navigate_to_location,
            "ros2_save_location": ros2_save_location,
            "recall_skill": recall_skill,
            "save_skill": save_skill,
            "search_docs": search_docs,
            "web_search": web_search,
        }

    def _execute_code(self, code: str, timeout: float = 15.0) -> dict:
        """
        Kodu kisitli bir isim uzayinda (in-process) calistirir.
        Her ros2_* / hafiza aracina yapilan cagri gercekten SafetyValidator'dan
        gecer (sadece metin uzerinde keyword taramasi degil).
        """
        call_log: list = []
        namespace = self._make_tool_namespace(call_log)
        output = io.StringIO()
        error_holder = {}

        def _run():
            try:
                with contextlib.redirect_stdout(output):
                    exec(code, namespace)
            except (ToolBlockedError, ToolExecutionError) as e:
                error_holder["error"] = str(e)
            except Exception as e:
                error_holder["error"] = f"{type(e).__name__}: {e}"

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            return {"success": False, "error": f"Zaman asimi ({timeout}s)", "call_log": call_log}
        if "error" in error_holder:
            return {"success": False, "error": error_holder["error"], "call_log": call_log}
        return {"success": True, "output": output.getvalue(), "call_log": call_log}

    def emergency_stop(self):
        """E-stop - validator'a ilet."""
        self.validator.emergency_stop()

    def _log(self, task, code, outcome, attempts):
        self.run_log.append({
            "timestamp": time.time(), "task": task,
            "outcome": outcome, "attempts": attempts,
            "code_length": len(code)
        })


# -- Test ------------------------------------------------------
if __name__ == "__main__":
    import os
    os.chdir(__import__("pathlib").Path(__file__).parent.parent)

    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    print(f"Ollama URL: {ollama_url}")

    try:
        import requests
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"[OK] Ollama erisilebilir. Modeller: {models}")
    except Exception as e:
        print(f"[ERR] Ollama erisilemiyor: {e}")
        print("  Ollama'yi baslat ve tekrar dene")
        exit(1)

    agent = AgentCore(ollama_url=ollama_url)
    print("\n[OK] Agent Core hazir")
    print(f"Skill kutuphanesi: {agent.skill_lib.stats()}")

    # Gercek uctan uca test: basit bir gorev calistir (ROS2 baglantisi olmadan,
    # kod sadece print/sleep gibi zararsiz seyler uretmeli - validator ve
    # sandbox calisiyor mu diye test eder)
    result = agent.run("2 sayisini ekrana yazdiran bir python kodu yaz ve calistir")
    print(f"\nSonuc: {result['status']}")
