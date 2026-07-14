"""ROSClaw - kapsamli bilesen bazli test scripti. Her bilesen icin PASS/FAIL raporlar."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


# 1. Validator
try:
    from core.validator import SafetyValidator
    v = SafetyValidator()
    r1 = v.validate("ros2_publish", {"topic": "/cmd_vel", "msg": {"linear": {"x": 0.3}, "angular": {"z": 0}}})
    r2 = v.validate("ros2_publish", {"topic": "/cmd_vel", "msg": {"linear": {"x": 10.0}, "angular": {"z": 0}}})
    r3 = v.validate("ros2_publish", {"topic": "/system/shutdown", "msg": {}})
    r4 = v.validate("ros2_publish", {"topic": "/cmd_vel", "msg": {"twist": {"linear": {"x": 10.0}, "angular": {"z": 0}}}})
    v.emergency_stop()
    r5 = v.validate("ros2_publish", {"topic": "/cmd_vel", "msg": {"linear": {"x": 0.1}, "angular": {"z": 0}}})
    v.release_estop()
    check("Validator: normal hiz ALLOW", r1.decision == "ALLOW")
    check("Validator: hiz asimi BLOCK", r2.decision == "BLOCK")
    check("Validator: izinsiz topic BLOCK", r3.decision == "BLOCK")
    check("Validator: TwistStamped icindeki hiz de kontrol ediliyor", r4.decision == "BLOCK")
    check("Validator: e-stop aktifken BLOCK", r5.decision == "BLOCK")
except Exception as e:
    check("Validator", False, str(e))

# 2. ROS2 Tool Registry + gercek baglanti
try:
    from tools.ros2_tools import ROS2ToolRegistry
    reg = ROS2ToolRegistry()
    manifest = reg.get_tool_manifest()
    check("ROS2ToolRegistry: manifest uretiliyor", "ros2_publish" in manifest)
    connected = reg.connect()
    check("ROS2ToolRegistry: gercek rosbridge baglantisi", connected)
    if connected:
        topics = reg.ros2_list_topics()
        check("ROS2ToolRegistry: gercek topic listesi", topics["status"] == "ok" and "/cmd_vel" in topics["topics"])

        twt = reg.ros2_topics_with_types()
        check("ROS2ToolRegistry: ros2_topics_with_types calisiyor",
              twt["status"] == "ok" and twt["topics"].get("/cmd_vel") == "geometry_msgs/msg/TwistStamped")

        details = reg.ros2_message_details("geometry_msgs/msg/TwistStamped")
        fieldnames = details["typedefs"][0]["fieldnames"] if details.get("typedefs") else []
        check("ROS2ToolRegistry: ros2_message_details dogru alanlari donduruyor",
              details["status"] == "ok" and "header" in fieldnames and "twist" in fieldnames)
except Exception as e:
    check("ROS2ToolRegistry", False, str(e))

# 3. Observation normalizer
try:
    from core.observation import ObservationNormalizer
    norm = ObservationNormalizer()
    result = norm.normalize("/scan", {"ranges": [0.3]*50 + [5.0]*310})
    check("ObservationNormalizer: laser normalize", result["sensor"] == "laser" and result["front_distance"] is not None)

    # Gercek rosbridge verisinde menzil disi olcumler (inf/NaN) JSON'a
    # cevrilirken None/null olur - bu, math.isinf(None)'da TypeError'a
    # yol acip get_front_distance()'in gercek robotta SESSIZCE None
    # donmesine (LiDAR guard/refleks katmaninin devre disi kalmasina)
    # sebep olan gercek bir uretim hatasiydi. Duzeltmenin kalicilastigini dogrula.
    ranges_with_none = [None]*140 + [1.2]*80 + [None]*140
    result_none = norm.normalize("/scan", {"ranges": ranges_with_none})
    check("ObservationNormalizer: None (inf/NaN) degerler cokmeden filtreleniyor",
          result_none["front_distance"] == 1.2)
except Exception as e:
    check("ObservationNormalizer", False, str(e))

# 4. Skill library (+ anti-poisoning guard)
try:
    from memory.skill_library import SkillLibrary
    import pathlib
    test_path = "logs/test_skills.json"
    if pathlib.Path(test_path).exists():
        pathlib.Path(test_path).unlink()
    lib = SkillLibrary(path=test_path)
    lib.save("1 metre ileri git", "kod_ileri")
    lib.save("2 sayisini yazdir", "kod_yazdir")
    r_exact = lib.recall("1 metre ileri git")
    r_opposite = lib.recall("1 metre geri git")
    r_diffnum = lib.recall("5 metre ileri git")
    check("SkillLibrary: tam eslesme bulunuyor", r_exact is not None)
    check("SkillLibrary: zit yon guard (ileri/geri karismiyor)", r_opposite is None)
    check("SkillLibrary: sayi guard (1 metre / 5 metre karismiyor)", r_diffnum is None)
    pathlib.Path(test_path).unlink()
except Exception as e:
    check("SkillLibrary", False, str(e))

# 5. Model router
try:
    from core.model_router import ModelRouter
    router = ModelRouter()
    simple = router._complexity_score("1 metre ileri git")
    complex_ = router._complexity_score("Ortami analiz et, tehlikeli nesneleri belirle, karar ver ve rota planla")
    check("ModelRouter: basit gorev dusuk karmasiklik", simple < 0.5, f"skor={simple:.2f}")
    check("ModelRouter: karmasik gorev yuksek karmasiklik", complex_ >= 0.7, f"skor={complex_:.2f}")
    internet = router._internet_available()
    check("ModelRouter: internet kontrolu calisiyor", isinstance(internet, bool))
except Exception as e:
    check("ModelRouter", False, str(e))

# 6. RAG knowledge base
try:
    from memory.rag_knowledge import RAGKnowledgeBase
    kb = RAGKnowledgeBase()
    stats = kb.stats()
    check("RAGKnowledgeBase: belgeler yuklu", stats["total_documents"] > 20, f"{stats['total_documents']} parca")
    result = kb.search("cmd_vel mesaj tipi twist stamped", top_k=1)
    check("RAGKnowledgeBase: TwistStamped bilgisi bulunuyor", "TwistStamped" in result)
except Exception as e:
    check("RAGKnowledgeBase", False, str(e))

# 7. search_docs / web_tools
try:
    from tools.search_docs import search_docs
    r = search_docs("gazebo paket adi jazzy")
    check("search_docs: yerel RAG calisiyor", r["status"] == "ok" and r["source"] == "local_rag")
except Exception as e:
    check("search_docs", False, str(e))

try:
    from tools.web_tools import web_search, _internet_available
    net = _internet_available()
    check("web_tools: internet kontrolu", isinstance(net, bool), f"internet={net}")
except Exception as e:
    check("web_tools", False, str(e))

# 8. Agent core - sandbox guvenlik testleri
try:
    from core.agent_core import AgentCore
    agent = AgentCore()
    agent.tools.connect()

    r_import = agent._execute_code('import os\nos.system("whoami")')
    check("AgentCore sandbox: import engelleniyor", not r_import["success"])

    r_speed = agent._execute_code('ros2_publish("/cmd_vel", {"twist": {"linear": {"x": 5.0}, "angular": {"z": 0.0}}}, "geometry_msgs/msg/TwistStamped")')
    check("AgentCore sandbox: hiz limiti asimi BLOCK ediliyor", not r_speed["success"] and "engellendi" in str(r_speed.get("error","")))

    r_bad_topic = agent._execute_code('ros2_publish("/sistem/kapat", {}, "std_msgs/msg/String")')
    check("AgentCore sandbox: izinsiz topic BLOCK ediliyor", not r_bad_topic["success"])
except Exception as e:
    check("AgentCore sandbox", False, str(e))

# 9. Kod bloğu olmadan uretilen kod dogru siniflendiriliyor mu (fence-less fallback)
try:
    from core.agent_core import AgentCore
    agent2 = AgentCore()
    code_no_fence = 'ros2_publish("/cmd_vel", {"twist": {"linear": {"x": 0.1}}})'
    chat_text = "Merhaba! Nasil yardimci olabilirim?"
    check("_extract_code: fence'siz gercek kodu taniyor",
          agent2._extract_code(code_no_fence) == code_no_fence)
    check("_extract_code: gercek sohbeti kod sanmiyor",
          agent2._extract_code(chat_text) is None)
except Exception as e:
    check("_extract_code fence-less fallback", False, str(e))

# 10. Robot profil sistemi: ekleme, degistirme, silme, guvenlik limiti override
try:
    from memory.robot_profiles import RobotProfileStore
    test_store_path = "logs/test_robot_profiles2.json"
    import pathlib
    pathlib.Path(test_store_path).unlink(missing_ok=True)
    store = RobotProfileStore(path=test_store_path)
    check("RobotProfileStore: varsayilan Gazebo profili otomatik olusuyor",
          len(store.list_profiles()) == 1 and store.get_active() is not None)

    new_id = store.add({"name": "Test", "host": "127.0.0.1", "port": 9090,
                         "robot_type": "generic", "velocity_limits": {"max_linear": 0.1},
                         "topic_allowlist": {"publish": [], "subscribe": []},
                         "movement_style": "unknown", "notes": ""})
    check("RobotProfileStore: yeni profil eklendi", store.get(new_id) is not None)
    store.set_active(new_id)
    check("RobotProfileStore: aktif profil degisti", store.active_id == new_id)
    store.delete(new_id)
    check("RobotProfileStore: profil silindi", store.get(new_id) is None)
    pathlib.Path(test_store_path).unlink(missing_ok=True)

    from core.validator import SafetyValidator
    val = SafetyValidator()
    val.apply_profile_overrides(velocity_limits={"max_linear": 0.1})
    r_over = val.validate("ros2_publish", {"topic": "/cmd_vel", "msg": {"linear": {"x": 0.2}, "angular": {"z": 0}}})
    check("Validator: profil override gercekten limiti degistiriyor", r_over.decision == "BLOCK")
except Exception as e:
    check("RobotProfileStore / override", False, str(e))

# 11. Gorev planlayici: bilesik algilama + bolme
try:
    from core.agent_core import AgentCore
    agent3 = AgentCore()
    check("TaskPlanner: basit talimat bilesik SANILMIYOR",
          not agent3._looks_compound("1 metre ileri git"))
    check("TaskPlanner: bilesik talimat DOGRU ALGILANIYOR",
          agent3._looks_compound("kirmizi topu al ve mavi kutuya birak"))

    steps = agent3._decompose("0.2 metre ileri git ve sonra dur")
    check("TaskPlanner: bilesik talimat 2 adima bolunuyor", len(steps) >= 2, f"{len(steps)} adim: {steps}")

    steps_simple = agent3._decompose("1 metre ileri git")
    check("TaskPlanner: basit talimat tek adim kaliyor", len(steps_simple) == 1)
except Exception as e:
    check("TaskPlanner", False, str(e))

# 12. LiDAR yakinlik korumasi + Audit Logger + Brain-Cerebellum refleks katmani
try:
    from core.validator import SafetyValidator
    from core.audit_logger import AuditLogger
    import pathlib

    # 12a. LiDAR guard: ileri hareket engelli, geri hareket ve uzak engelde ileri serbest
    v2 = SafetyValidator()
    r_close_forward = v2.validate("ros2_publish", {"topic": "/cmd_vel",
        "msg": {"linear": {"x": 0.2}, "angular": {"z": 0}}, "front_distance": 0.1})
    r_close_backward = v2.validate("ros2_publish", {"topic": "/cmd_vel",
        "msg": {"linear": {"x": -0.2}, "angular": {"z": 0}}, "front_distance": 0.1})
    r_far_forward = v2.validate("ros2_publish", {"topic": "/cmd_vel",
        "msg": {"linear": {"x": 0.2}, "angular": {"z": 0}}, "front_distance": 1.5})
    check("Validator: LiDAR yakin engelde ileri hareket BLOCK", r_close_forward.decision == "BLOCK")
    check("Validator: LiDAR yakin engelde geri hareket ALLOW", r_close_backward.decision == "ALLOW")
    check("Validator: LiDAR uzak engelde ileri hareket ALLOW", r_far_forward.decision == "ALLOW")

    # 12b. Audit logger: kalici JSONL, makale formulu (t,o_t,u_t,d_t,r_t,y_t), stats
    test_audit_path = "logs/test_audit_full.jsonl"
    pathlib.Path(test_audit_path).unlink(missing_ok=True)
    logger = AuditLogger(path=test_audit_path)
    logger.log({"front_distance": 1.2}, "ros2_publish", {"topic": "/cmd_vel"}, "ALLOW", "guvenli", outcome="success")
    logger.log({"front_distance": 0.1}, "ros2_publish", {"topic": "/cmd_vel"}, "BLOCK", "engel yakin", outcome=None)
    entries = logger.read_all()
    stats = logger.stats()
    check("AuditLogger: kayitlar kaliciyor (JSONL)", len(entries) == 2)
    check("AuditLogger: formul alanlari dogru (t,o_t,u_t,d_t,r_t,y_t)",
          all(k in entries[0] for k in ("t", "o_t", "u_t", "d_t", "r_t", "y_t")))
    check("AuditLogger: stats dogru sayiyor", stats["total_entries"] == 2 and stats["total_blocked"] == 1)
    pathlib.Path(test_audit_path).unlink(missing_ok=True)

    # 12c. Refleks katmani: LLM'den bagimsiz, dogrudan sensor callback'inden e-stop
    from core.agent_core import AgentCore
    agent4 = AgentCore()
    agent4.tools.connect()
    check("Refleks: baslangicta e-stop kapali", not agent4.validator._estop_active)
    agent4._on_reflex_trigger(0.05)  # acil esik (0.15m) altinda
    check("Refleks: kritik yakinlikta e-stop otomatik tetikleniyor", agent4.validator._estop_active)
    agent4.validator.release_estop()
    agent4._on_reflex_trigger(1.0)  # esik ustunde - tetiklenmemeli
    check("Refleks: esik ustundeyken e-stop tetiklenmiyor", not agent4.validator._estop_active)
except Exception as e:
    check("LiDAR guard / AuditLogger / Refleks", False, str(e))

print()
print("="*60)
passed = sum(1 for _,s,_ in results if s == "PASS")
failed = sum(1 for _,s,_ in results if s == "FAIL")
print(f"TOPLAM: {passed} basarili, {failed} basarisiz (toplam {len(results)} test)")
if failed:
    print("\nBASARISIZ OLANLAR:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  - {name}: {detail}")
