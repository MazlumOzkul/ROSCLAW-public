# ROSClaw

Humanoid robot icin agentic AI sistemi: kendi ROS2/Python kodunu ureten,
hata olursa duzelten, basarili cozumleri kalici hafizaya kaydeden ve
internet varsa/yoksa dogru modele yonlenen hibrit bir mimari.

## Su anki durum: TAM CALISIR DURUMDA (simulasyon)

Windows tarafindaki "beyin" ve WSL2 tarafindaki ROS2/Gazebo simulasyonu
birbirine bagli ve uctan uca test edildi: web arayuzunden "0.5 metre ileri
git" komutu gonderildi, Qwen2.5-Coder kodu uretti, validator onayladi,
TurtleBot3 Gazebo'da GERCEKTEN hareket etti (odom ile dogrulandi: x 0 -> 0.48m).

| Bilesen | Durum |
|---|---|
| Ollama (qwen2.5-coder:7b, gemma4:e4b), `OLLAMA_HOST=0.0.0.0` | Calisiyor (Windows) |
| `core/validator.py` - guvenlik dogrulayici | Gercek robot komutlarinda devrede |
| `tools/ros2_tools.py` - ROS2 arac seti | **rosbridge'e bagli, gercek robotu kontrol ediyor** |
| `core/observation.py` - sensor normalizer | Test edildi |
| `memory/skill_library.py` - deneyim hafizasi | Test edildi (yanlis-eslesme koruma dahil) |
| `core/agent_core.py` - AOR dongusu | Gercek ROS2 ile uctan uca test edildi |
| `core/model_router.py` - hibrit router | Test edildi |
| `memory/rag_knowledge.py` - ChromaDB RAG | Test edildi |
| `tools/search_docs.py` / `tools/web_tools.py` | Test edildi (offline+online) |
| `gateway/api.py` + `web_ui.html` | Calisiyor (http://localhost:8000) |
| WSL2 (Ubuntu-24.04, root kullanici) | Kurulu |
| ROS2 Jazzy Desktop | Kurulu, talker/listener testi gecti |
| Gazebo (ros_gz / Gazebo Sim) + TurtleBot3 | Kurulu, `/cmd_vel`, `/odom`, `/scan` calisiyor |
| rosbridge_websocket (port 9090) | Kurulu, Windows'tan `localhost:9090` ile erisiliyor |
| Robot baglanti secici (WiFi tarzi) | Calisiyor - ag tarama, profil kaydetme, calisirken robot degistirme |
| LiDAR yakinlik korumasi (`/scan` -> validator) | Gercek Gazebo LiDAR verisiyle test edildi |
| `core/audit_logger.py` - kalici JSONL audit log (l_t formulu) | Test edildi (uctan uca 4+ gercek kayit dogrulandi) |
| Brain-Cerebellum refleks katmani (sensor-tetiklemeli e-stop) | Test edildi - LLM'den bagimsiz calisiyor |
| `logs/benchmark.py` - kategorize/olculmus test | Calisiyor |
| Kollu robot (turtlebot3_manipulation, Gazebo Sim portu) | Calisiyor - `sim/turtlebot3_manipulation_gz/` |
| `tools/arm_kinematics.py` - ozel sayisal IK (Kartezyen kol kontrolu) | Test edildi (0.00cm hata) |
| `ros2_move_arm_to_pose` / `ros2_gripper` araclari | Gercek FollowJointTrajectory/GripperCommand action'lariyla test edildi |
| `tools/object_detection.py` - kamera tabanli renk tespiti (offline) | Test edildi (kirmizi top, 3D projeksiyon) |
| Uctan uca "X topu al" (kamera+kol+gripper+LLM) | Gercek Qwen2.5-Coder ile dogal dilden test edildi |
| `tools/object_recognition.py` - YOLO-World acik-kelime tanima | Gercek fotografla dogrulandi (%92 guven) - simulasyonda sim-to-real farki nedeniyle gorsel demo yok |
| `tools/depth_estimation.py` - Depth Anything V2 gercek derinlik | Calisiyor (~9s/kare, CPU) - simulasyonda dogruluk sim-to-real farkindan etkileniyor |
| `tools/grasp_planning.py` - tutulabilirlik kontrolu | Calisiyor - genis nesneler icin durustce reddediyor |

## Robota baglanma - herhangi bir ROS2 robotu (WiFi ag secici gibi)

Web arayuzunde saga ustteki **"Robota Baglan"** butonu bir WiFi ag secici
gibi calisir - G1'e ozel degil, rosbridge acan HERHANGI bir ROS2 robotu
icin genellenmis:

1. **"Ag Tara"** - yerel agdaki (ve localhost'taki) tum cihazlarda rosbridge
   portunu (9090) arar, bulduklarini gercekten rosbridge olup olmadigini
   dogrulayarak listeler (`tools/discovery.py`). Robot markasi/modeli onemli
   degil - hepsi ayni sekilde bulunur.
2. **Kayitli Robotlar** - daha once eklenen profiller (WiFi'de "bilinen
   aglar" gibi) listelenir, tek tikla baglanilir (`memory/robot_profiles.py`).
3. **Elle Ekle** - tarama bulamazsa (farkli subnet, vs.) isim/IP/port girip
   robot tipini secerek (Gazebo, TurtleBot3, Unitree G1, Genel) eklenir -
   secilen tipe gore guvenlik limitleri ve izinli topic listesi otomatik
   dolar, istenirse degistirilebilir.
4. Bir profile baglanildiginda `core/agent_core.py`'nin `switch_robot()`
   metodu: mevcut baglantiyi kapatir (reactor'u DURDURMADAN - bkz.
   `tools/ros2_tools.py` disconnect() yorumu, Twisted'in reactor'u
   process icinde yeniden baslatamamasi sorununu cozuyor), yeni robota
   baglanir, o robotun hiz limitlerini/izinli topic'lerini `SafetyValidator`
   uzerinde devreye alir ve kod uretim prompt'unu (`get_tool_manifest`)
   o robotun hareket tarzina (twist_stamped / unitree_sport / bilinmiyor)
   gore uyarlar.

Boylece G1, TurtleBot3 veya baska bir ROS2 robotu arasinda gecis yapmak
kod degistirmek degil, arayuzden birkac tikla robot secmek anlamina gelir.

### Bilinmeyen robotlarda calisirken kesif (capability discovery)

Robotun hareket formati onceden taniml/eslesmemisse (`movement_style:
"unknown"`), agent tahmin etmiyor - `tools/ros2_tools.py`'deki
`ros2_topics_with_types()` (tum topic'leri GERCEK mesaj tipleriyle) ve
`ros2_message_details()` (bir mesajin tam alan yapisi - `ros2 interface
show`'un ROS2 agenti icin karsiligi) araclariyla calisirken kesfeder. Bu
bilgi guvenilirlik icin `core/agent_core.py`'de KOD SEVIYESINDE, deterministik
olarak modele veriliyor - kucuk yerel modellerin "muhtemelen boyledir" diye
tahmin etmesine (ve yanlis cikmasina) birakmiyoruz.

## Cok adimli/bilesik gorevler (gorev planlayici)

"Kirmizi topu birak ve mavi topu al" gibi BIRDEN FAZLA ayri eylem iceren
talimatlar, `core/agent_core.py`'deki `run()` tarafindan otomatik olarak
ayri, atomik alt-gorevlere bolunur (`_decompose()`) ve her biri KENDI
guvenlik dogrulamasi + hafiza kontrolu + yeniden deneme dongusuyle sirayla
calistirilir (`_run_single()`). Bu, tek bir buyuk kod blogunun butun
coklu-adim mantigini hatasiz uretmesini beklemekten cok daha guvenilir -
onceki bir hatada modelin "once tekrar al, sonra birak" gibi yanlis bir
sira uretmesi tam da bu yuzden olmustu.

- Bilesik talimat sezgisel olarak ("ve", "sonra", "ardindan" gibi baglaclarla)
  once ucuz bir kontrolle tespit edilir - basit tek-eylemli talimatlarda
  (buyuk cogunluk) ekstra LLM cagrisi YAPILMAZ.
- Bilesik gorunuyorsa, Qwen'e "bunu adimlara bol" diye sorulur; sonuc
  `skills/task_plans.json`'da (SkillLibrary'nin ayni embedding+kategori-guard
  altyapisi yeniden kullanilarak) onbelleklenir - ayni bilesik talimat
  tekrar gelirse bolme adimini bile atlar.
- Bir adim basarisiz olursa (`partial_failure`), kalan adimlar calistirilmaz,
  hangi adima kadar tamamlandigi raporlanir - web arayuzunde her adim
  ayri ayri ✓/✗ ile gosterilir.

## Guvenlik ve gozlemlenebilirlik katmani (C = <A, O, V, L> sozlesmesinin L'i + arXiv 2603.26997'deki keep-out/reflex kavramlari)

Makalenin sozlesmesini ve guvenlik mimarisini daha da tamamlamak icin uc
bilesen eklendi - hepsi gercek Gazebo/TurtleBot3 LiDAR verisiyle test edildi:

### 1. LiDAR yakinlik korumasi ("keep-out zone")

`tools/ros2_tools.py` baglanti kurulunca `/scan` topic'ine KALICI olarak
abone olur (`_subscribe_scan_background`) ve her mesajda en yakin on
mesafeyi hesaplar (`get_front_distance()`, `core/observation.py`'deki
normalizer'i kullanarak). Her `ros2_publish` cagrisindan once
`core/agent_core.py` bu mesafeyi otomatik olarak arac argumanlarina ekler;
`core/validator.py`'deki `_validate_publish()` onde `lidar_stop_distance`
(varsayilan 0.3m) altinda bir engel varken **SADECE ileri hareketi**
bloklar - geri gitmek veya donmek serbest kalir (engelden uzaklasmayi
engellemek robotu kilitlemek olurdu). Esikler `config/safety_config.yaml`
-> `safety_zones` altinda.

### 2. Kalici JSONL audit logger (makaledeki l_t = (t, o_t, u_t, d_t, r_t, y_t) formulu)

`core/audit_logger.py`, her arac cagrisini calismadan ONCE bile
(`AuditLogger.log()`) `logs/audit_log.jsonl`'a append-only olarak yazar:
zaman damgasi, karar aninda bilinen gozlem (`o_t`, orn. on mesafe), onerilen
arac cagrisi (`u_t`), karar (`d_t`: ALLOW/BLOCK), gerekce (`r_t`) ve
calisma sonucu (`y_t`: success/error/None - BLOCK edildiyse hic calismadi).
Boylece BLOCK edilen girisimler bile post-hoc analiz icin kaybolmuyor
(I3 - Auditability invariant'i). `AuditLogger.stats()` toplam
ALLOW/BLOCK sayisini, en cok tekrarlanan BLOCK gerekcelerini ve arac
kullanim dagilimini ozetler.

### 3. "Brain-Cerebellum" refleks katmani (LLM'den bagimsiz anlik e-stop)

Makaledeki "yavas serebral (LLM) karar dongusu / hizli serebellar refleks"
ayrimindan esinlenildi: `/scan` mesaji geldiginde, eger on mesafe
`lidar_emergency_stop_distance` (varsayilan 0.15m) altindaysa,
`tools/ros2_tools.py`'nin **roslibpy'nin kendi sensor callback thread'i
icinden**, `core/agent_core.py`'deki `_on_reflex_trigger()`'i cagirarak
DOGRUDAN `SafetyValidator.emergency_stop()`'u tetikler - LLM'in bir sonraki
kararini beklemez, agentin dongusune hic girmez. Bu, en kritik guvenlik
kararinin en yavas bilesenin (LLM cagrisi, saniyeler surebilir) hizina
bagli kalmamasini saglar.

### Kategorize/olculmus test benchmarki

`logs/benchmark.py`, makalenin degerlendirme metodolojisinden esinlenerek
(akademik olcekte degil, pratik N=3 tekrarla) uc kategoride olcum yapar:
yapisal (net komutlarda tamamlama orani), acik-uclu (belirsiz komutlarda
agentin makul kod uretme orani) ve guvenlik (kasitli tehlikeli isteklerin
validator tarafindan BLOK edilme orani - %100 hedeflenir). Ayrica skill
cache hit oranini da olcup `logs/benchmark_report.json`'a yazar. Calistirmak
icin: `.venv\Scripts\python.exe logs\benchmark.py` (Ollama ve Gazebo/rosbridge
calisiyor olmali).

Tum bunlar `logs/full_test.py`'deki otomatik regresyon testlerine de
eklendi (44 test, hepsi PASS) - LiDAR guard'in ileri/geri davranisi,
audit logger'in kalicilik ve formul dogrulugu, refleks katmaninin esik
uzerinde/altinda dogru tetiklenmesi ayri ayri dogrulaniyor.

## Kollu robot: kol kontrolu + kamera tabanli nesne tutma

TurtleBot3 Waffle Pi tabanina OpenManipulator-X kolu monte edilmis
resmi ROBOTIS paketi (`ros-jazzy-turtlebot3-manipulation`) Gazebo Sim
(`ros_gz`) icin portlandi - vendor paketi klasik Gazebo hedefliyordu
(bkz. `sim/turtlebot3_manipulation_gz/` klasorundeki dosyalarin
docstring'leri, her birinde tam olarak hangi vendor hatasinin
duzeltildigi yazili).

### Neden MoveIt2 degil de kendi IK cozucumuz

`turtlebot3_manipulation_moveit_config` paketinde vendor'un kendi
config dosyalarinda birden fazla hata bulundu (`request_adapters` yanlislikla
tek string olarak tanimliydi, `ompl_planning.yaml` hala Franka Panda
ornek sablonundan kalma grup isimleri iceriyordu, `pilz_cartesian_limits.yaml`
hic yoktu) - bunlarin hepsini duzelttikten sonra bile move_group
rclcpp'nin ic parametre namespace cozumlemesinde daha derin bir sorunla
cokmeye devam etti. Bunun yerine `tools/arm_kinematics.py`, OpenManipulator-X'in
gercek URDF eklem/link degerleriyle KENDI sayisal (Levenberg-Marquardt,
scipy) ters kinematigini cozer - MoveIt2/ROS'a hic bagimli degil, saf
numpy/scipy. Gercek robotta test edildi: hedef (0.25, 0.05, 0.15) ->
gercek konum farki 0.00cm.

### Yeni araclar

- `ros2_move_arm_to_pose(x, y, z, duration_sec=2.0)` - kolun ucunu
  base_link cercevesinde verilen Kartezyen konuma goturur (IK + gercek
  `FollowJointTrajectory` action'i). Erisim ~0.35m, disina cikan/masaya
  cok yakin/cok yuksek hedefler `SafetyValidator` tarafindan reddedilir.
- `ros2_gripper(position, max_effort=5.0)` - gripper ac/kapat
  (`GripperCommand` action'i).
- `ros2_detect_object(color, plane_z=0.0)` - kameradan tek kare alip
  offline HSV renk esiklemeyle (bilinen renkler: kirmizi/mavi/yesil/sari)
  en buyuk nesnenin merkezini bulur, sabit kamera-govde offseti +
  camera_info kalibrasyonu kullanarak piksel konumunu base_link
  cercevesinde 3D (x,y,z) noktasina projekte eder (duzlem-kesisim
  yontemi - tek RGB kameradan gercek derinlik olculmez, `plane_z`
  parametresiyle masanin/zeminin yaklasik yuksekligi varsayilir).

Uctan uca "kirmizi topu al" komutu gercek Qwen2.5-Coder ile dogal
dilden test edildi: model `ros2_detect_object` -> `ros2_gripper` ->
`ros2_move_arm_to_pose` zincirini kendi kod uretip calistirdi;
validator ilk denemede erisim-disi bir hedefi dogru sekilde
bloklayinca, AOR dongusu farkli bir stratejiyle (once taban hareketi)
tekrar deneyip basardi.

### Bilinen sinirlama - Gazebo Sim'de kamera icin dunya dosyasi

Gazebo Sim'in varsayilan `empty.sdf` dunyasinda render-tabanli
sensorler (kamera, LiDAR) icin gereken `gz-sim-sensors-system` eklentisi
YOK - bu sessizce, HATA VERMEDEN kameranin (ve potansiyel olarak
LiDAR'in) hicbir veri uretmemesine yol aciyordu. `sim/turtlebot3_manipulation_gz/rosclaw_world.sdf`
bu eklentiyi (+ imu-system) ekleyen kendi minimal dunyamiz - kollu robotu
baslatirken vendor'un `empty.sdf`'i yerine bu dosya kullanilmali.

## Gercek nesne tanima + tutulabilirlik kontrolu (renk-bazli degil)

`ros2_detect_object` (renk-bazli, HSV) yaninda, GERCEK acik-kelime nesne
tanima eklendi: `ros2_find_object(description)` - "kirmizi top" degil
"cup", "box", "vacuum cleaner" gibi serbest metinle nesne TIPI arar.

- **`tools/object_recognition.py`** - YOLO-World (`yolov8s-worldv2`,
  Ultralytics, 12.7M parametre). Acik-kelime: onceden tanimlanmis bir
  sinif listesiyle sinirli degil, HERHANGI bir metin sorgusuyla calisir.
  Agirliklar (~28MB) ilk kullanimda bir kere iner, sonrasi tamamen offline.
- **`tools/depth_estimation.py`** - Depth Anything V2 (Metric-Indoor-Small,
  25M parametre, HuggingFace transformers). Tek RGB kareden GERCEK
  (metre cinsinden) derinlik - eski "duz zemin varsayimi" yerine.
- **`tools/grasp_planning.py`** - tutulabilirlik kontrolu. OpenManipulator-X'in
  bilekte DONDURME (roll) ekseni OLMADIGI icin (bkz. `arm_kinematics.py`),
  GG-CNN gibi kavrama-acisi tahmin eden modeller bu donanimda fiziksel
  olarak uygulanamaz - bunun yerine nesnenin tahmini genisligi gripper'in
  bilinen maksimum acikligiyla (~4.5cm, muhafazakar tahmin) karsilastirilir.
  Cok genis nesneler icin sahte bir "basarili" gorunumu yerine acikca
  "tutulamiyor" (`"graspable": false`) dondurulur.

### Bilinen sinirlama - "sim-to-real" farki (dogrulandi)

Bu iki model **gercek fotograflarda test edildi ve dogru calisti**
(YOLO-World, COCO test goruntusunde kedi/uzaktan kumanda gibi nesneleri
**%92 guvenle** dogru tespit etti). Ama **Gazebo Sim'in render motoru**
gercek kameralardan cok farkli (duz aydinlatma, basitlestirilmis dokular,
gercekci golge/yansima yok) - bu yuzden **hem renkli topta hem gercek
dokulu bir karton kutuda simulasyon icinde SIFIR guvenle bile hicbir sey
tespit edilemedi**. Bu, robotik arastirmasinda iyi bilinen, belgelenmis bir
problem - kod hatasi degil. Kod gercek fotograflarla dogrulandi ve **gercek
robotta/gercek kamerada dogrudan calismasi beklenir**; simulasyonda gorsel
ucdan-uca demo yapilamiyor. Renk-bazli `ros2_detect_object` (HSV esikleme,
dokudan bagimsiz) bu yuzden simulasyon testleri icin ayrica tutuldu.

## Navigasyon (SLAM + Nav2 + isimli konumlar)

Robot artik isimli konumlar arasinda otonom gidebiliyor - WiFi ag
kaydetmek gibi: bir yere gidip `ros2_save_location("mutfak")` dersin,
sonra istedigin zaman `ros2_navigate_to_location("mutfak")` ile oraya
gonderirsin.

- **`memory/location_store.py`** - isimli konumlari (`x,y,yaw`, harita
  cercevesinde) `config/locations.json`'da saklar - `RobotProfileStore`
  ile ayni JSON-store deseni.
- **`ros2_save_location(name)`** - `/amcl_pose`'dan o anki konumu okuyup
  kaydeder.
- **`ros2_navigate_to_location(name)`** - kayitli konumu Nav2'nin
  `/navigate_to_pose` action'ina gonderir; kayitsiz bir isim istenirse
  hatayi acikca bildirir ("once ros2_save_location ile kaydet").
- 3 odali (`salon`/`mutfak`/`yatak_odasi`) test evi `sim/turtlebot3_manipulation_gz/rosclaw_world.sdf`
  icinde tanimli; harita `slam_toolbox` ile cikarilip `nav2_map_server`
  ile kaydedildi, Nav2 bringup `nav2_bringup/bringup_launch.py` ile
  ozel bir `nav2_params.yaml` (kapida guvenli gecis icin `inflation_radius`
  dusuruldu, kapi genislikleri buyutuldu) kullaniyor.

### Cozulen kritik hata: Nav2 "SUCCEEDED" diyor ama robot hic hareket etmiyordu

Aylar suren bu fazin en onemli bulgusu: Nav2 `navigate_to_pose` "SUCCEEDED"
donduruyordu ama robotun GERCEK (gz ground-truth) konumu hic degismiyordu.
Kok neden: Jazzy'deki Nav2'nin `enable_stamped_cmd_vel` parametresi
varsayilan olarak kapali - yani `controller_server`, `behavior_server`,
`velocity_smoother`, `collision_monitor` ve `docking_server` duz
`geometry_msgs/Twist` yayinliyordu, ama robotun gz-native `DiffDrive`
eklentisi `TwistStamped` bekliyordu (bkz. yukaridaki "/cmd_vel mesaj
formati" bolumu) - mesaj sessizce yok sayiliyordu. Duzeltme: bu 5 nodun
HEPSINDE (sadece controller_server'da degil - bu topic'in tumune
publisher/subscriber olan her node'da tutarli olmasi gerekiyor, aksi
halde DDS "incompatible type" hatasi veriyor) `nav2_params.yaml`'da
`enable_stamped_cmd_vel: true` ayarlandi. Dogrulama: `/cmd_vel` artik
`TwistStamped` raporluyor, gercek hiz komutlari yayinlaniyor, ve robotun
gz ground-truth konumu navigasyon sirasinda GERCEKTEN degisiyor
(oncesinde tum oturum boyunca sifir hareket vardi).

### Bilinen sinirlama - AMCL lokalizasyon hassasiyeti

Genis, duz duvarli/az-ozellikli odalarda (ozellikle kapi esikleri gibi
simetrik/dar koridorlarda) AMCL'nin parcacik filtresi bazen ~1m'ye kadar
gercek konumdan sapabiliyor - Nav2 "hedefe ulasildi" diyebilir ama
ground-truth konum kaydedilen noktadan ~1m uzakta olabilir. Bu, lidar
tabanli lokalizasyonun bilinen bir sinirlamasi (kod hatasi degil) -
gercek robotta daha zengin ortam ozellikleri (mobilya, duzensiz duvarlar)
bu sapmayi tipik olarak azaltir. Test evi haritasi `slam_toolbox` ile
tum ev (salon+mutfak+yatak_odasi) dikkatli/yavas gezilerek cikarildi ve
gorsel olarak dogrulandi (once sadece salon+kismi mutfak kapsayan,
seyrek/eksik bir ilk harita vardi - bu, kapi esiginde navigasyonun
guvenilmez calismasina neden oluyordu).

## Nasil calistirilir

**Otomatik (varsayilan artik bu):** Windows oturum acilisinda "ROSClaw-AutoStart"
adinda bir Gorev Zamanlayici (Task Scheduler) gorevi otomatik olarak
`start_all.ps1`'i calistirir - Ollama hazir olmasini bekler, WSL2'de Gazebo
ve rosbridge'i ayri pencerelerde acar, sonra Gateway'i baslatir. Birkac
dakika icinde http://localhost:8000 hazir olur.

Gorevi kaldirmak/devre disi birakmak istersen:
```powershell
Unregister-ScheduledTask -TaskName "ROSClaw-AutoStart" -Confirm:$false
```

**Elle calistirmak istersen** (orn. oturum acmadan hemen test etmek icin):
```powershell
cd C:\ROSCLAW
.\start_all.ps1
```
veya adim adim:
```powershell
.\start_ros2_sim.ps1   # Gazebo + rosbridge (WSL2, ayri pencereler)
.\start.ps1            # Gateway
```

Tarayicida ac: http://localhost:8000

**Not:** Ollama'nin `OLLAMA_HOST=0.0.0.0` ile calismasi (WSL2 erisimi icin)
kalici bir Windows kullanici degiskeni olarak ayarlandi ve Ollama zaten
oturum acilisinda kendiliginden basliyor (Baslangic klasorundeki kisayol).

## Mimari (C = <A, O, V, L> sozlesmesi)

1. **Talimat gelir** (kendi web UI'imiz - harici uygulama/Telegram yok) -> `core/agent_core.py`
2. **Skill kutuphanesine bakilir** (`memory/skill_library.py`) - benzer bir
   gorev daha once basariyla yapildiysa, LLM'e gitmeden dogrudan o kod
   calistirilir (embedding benzerligi + sayi/zit-yon guardi ile korunur).
3. **Yoksa Ollama (qwen2.5-coder:7b) kod uretir** - `core/model_router.py`
   gorev karmasik ve internet varsa Claude API'ye (frontier) yonlendirebilir.
4. **Uretilen kod kisitli bir sandbox'ta calisir** (`agent_core._execute_code`):
   - `import` ifadeleri calismaz (guvenlik icin devre disi)
   - Sadece onceden tanimli araclar cagrilabilir: `ros2_publish`, `ros2_subscribe`,
     `ros2_service`, `ros2_action`, `ros2_get_param/set_param`, `ros2_list_topics`,
     `ros2_camera`, `recall_skill`, `save_skill`, `search_docs`, `web_search`
   - Her arac cagrisi calismadan ONCE `core/validator.py` icinden gecer
     (hiz limiti, topic allowlist, e-stop kontrolu) - **gercekten devrede**,
     sadece metin taramasi degil, her ros2_publish cagrisinin gercek hiz/topic
     degerlerini kontrol eder.
5. **Basarili olursa** kod `skill_library`'ye kaydedilir (bir dahaki sefere
   sifirdan uretilmez). **Basarisiz olursa** hata mesaji modele geri
   verilir, model kodu duzeltip tekrar dener (5 deneme - AOR dongusu).
6. **search_docs / web_search**: Agent teknik bilgiye ihtiyac duyarsa once
   yerel ChromaDB RAG deposuna (`memory/rag_knowledge.py`) bakar (tamamen
   offline). Internet varsa ek kaynak olarak web aramasi da yapabilir,
   internet yoksa veya sonuc bulunamazsa otomatik olarak yerel RAG'a duser.

## Onemli: /cmd_vel mesaj formati

ROS2 Jazzy + guncel Gazebo (Gazebo Sim / ros_gz) kurulumunda `/cmd_vel`
**duz `geometry_msgs/Twist` DEGIL**, `geometry_msgs/msg/TwistStamped` bekler.
Hiz degerleri `msg["twist"]["linear"/"angular"]` altinda olmali:

```python
ros2_publish("/cmd_vel",
    {"twist": {"linear": {"x": 0.2, "y": 0.0, "z": 0.0},
               "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}},
    "geometry_msgs/msg/TwistStamped")
```

Bu, `core/agent_core.py` SYSTEM_PROMPT'una ve `tools/ros2_tools.py` arac
manifestine ornekle birlikte eklendi - model bunu dogru formatta uretiyor.
Duz Twist formati gonderilirse mesaj sessizce yok sayilir, robot hareket
etmez (validator hata vermez, ama fiziksel etki olmaz - bunu fark etmek
zaman aldi, dikkat).

## WSL2 ortami notlari

- Ubuntu-24.04, **root** kullanicisiyla calisiyor (interaktif kullanici
  olusturma sihirbazi bilinerek atlandi - kisisel gelistirme ortami icin
  sorun degil).
- `ip route show | grep default` ile bulunan gateway IP'si (orn.
  `172.31.208.1`) WSL2'den Windows'a; `localhost` (WSL2'nin localhost
  forwarding ozelligi sayesinde) Windows'tan WSL2'ye erisim icin kullanilir.
- Gazebo/rosbridge gibi arka plan surecleri `wsl.exe` baglantisi kapaninca
  sonlanabiliyor - bu yuzden `start_ros2_sim.ps1` her ikisini de KENDI
  penceresinde acar (kapatmayin, calismaya devam etmeleri gerekiyor).
- `apt-cache search ros-jazzy | grep gazebo` ile dogru paket adlarini
  bulduk: eski `gazebo-ros-pkgs` yerine Jazzy'de `ros-jazzy-ros-gz`,
  `ros-jazzy-ros-gz-sim`, `ros-jazzy-gz-ros2-control` kullaniliyor.

## Gercek robota gecis

Robot baglantisi artik **tamamen `.env` uzerinden** ayarlaniyor - kod
degismiyor:

```env
ROS2_HOST=192.168.123.99   # robotun IP adresi (Gazebo icin: localhost)
ROS2_PORT=9090             # rosbridge portu
```

Ayrica `config/safety_config.yaml` icinde:

```yaml
environment: real_robot  # simulation -> real_robot
velocity_limits:
  max_linear: 0.3
  max_angular: 0.8
```

### Unitree G1 icin ozel notlar (arastirildi, henuz test edilmedi - donanim bekleniyor)

- G1, standart ROS2 RMW yerine **CycloneDDS** kullanir ve resmi olarak
  **Ethernet kablo** baglantisi + sabit IP (`192.168.123.99`) onerir. Mobil
  kullanim icin yerel WiFi de mumkun (gecikme Ethernet'ten fazla ama
  yuksek-seviye komutlar icin sorun degil).
- Iki kontrol seviyesi var: **yuksek seviye** (`/api/sport/request` -
  yuru/dur/otur gibi, dengeyi robot kendi yonetir) ve **dusuk seviye**
  (`/lowcmd` - motor bazinda tork/pozisyon). LLM'in serbestce kod uretmesine
  SADECE yuksek seviye acilmali - `config/safety_config.yaml`'daki
  `topic_allowlist` guncellenip `/lowcmd` KESINLIKLE eklenmemeli.
  Detay: github.com/unitreerobotics/unitree_ros2
- Gercek donanim gelince: G1'in oldugu ag/bilgisayarda ROS2 + `unitree_ros2`
  + `rosbridge_websocket` kurulmasi, `core/agent_core.py` SYSTEM_PROMPT'unun
  G1'in hareket API'sine gore guncellenmesi ve fiziksel bir e-stop butonu
  (yazilimsal e-stop tek basina yetersiz - dusme riski var) gerekiyor.

## Claude API (frontier model) icin

`.env` dosyasindaki `ANTHROPIC_API_KEY` degerini gercek anahtarinla
degistir - **onemli:** `.env` artik `core/agent_core.py` import edildiginde
otomatik yukleniyor (`load_dotenv()`), ayrica elle bir sey yapmana gerek yok.
Internet varsa ve gorev karmasikligi esigi (0.7) asilirsa
`core/model_router.py` otomatik olarak Claude API'ye yonlendirir; API
anahtari yoksa veya cagr basarisiz olursa sessizce Qwen2.5-Coder'a
(offline) duser.
