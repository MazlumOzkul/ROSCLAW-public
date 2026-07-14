"""
ROSClaw Ag Tarama - WiFi tarzi robot kesfi

Yerel ag altinda rosbridge_websocket calistiran cihazlari bulur. Robot
markasi/modeli fark etmeksizin calisir - cunku ROSClaw'in tum robot
entegrasyonu rosbridge uzerinden yapiliyor (bkz. tools/ros2_tools.py).
Bir robot ne olursa olsun rosbridge acik oldugu surece bu tarama onu bulur.
"""

import socket
import ipaddress
import concurrent.futures
import roslibpy


def _local_subnet() -> str:
    """Bu bilgisayarin bulundugu /24 subnet'i tahmin et (orn. 192.168.1.0/24)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()
    parts = local_ip.split(".")
    return ".".join(parts[:3]) + ".0/24"


def _check_port(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _guess_robot_type(topics: list) -> str:
    """Topic imzasina bakarak olasi robot tipini tahmin et (kesin degil, oneri)."""
    topic_set = set(topics)
    if "/api/sport/request" in topic_set or "/sportmodestate" in topic_set:
        return "unitree_g1"
    if "/cmd_vel" in topic_set and "/scan" in topic_set and "/odom" in topic_set:
        return "turtlebot3_real"
    return "generic"


def _verify_rosbridge(host: str, port: int, timeout: float = 2.0) -> dict:
    """Portun gercekten calisir bir rosbridge oldugunu dogrula, topic listesini al."""
    client = None
    try:
        client = roslibpy.Ros(host=host, port=port)
        client.run(timeout=timeout)
        if not client.is_connected:
            return {"verified": False}
        topics = client.get_topics()
        return {"verified": True, "topics": topics,
                "robot_type_guess": _guess_robot_type(topics)}
    except Exception:
        return {"verified": False}
    finally:
        if client is not None:
            try:
                client.terminate()
            except Exception:
                pass


def scan_for_robots(port: int = 9090, subnet: str = None, max_workers: int = 60) -> list:
    """
    Yerel agi (ve localhost'u) tarar, belirtilen portu acik olan cihazlari
    bulur, bulunanlarin gercekten rosbridge olup olmadigini dogrular.
    WiFi'de "ag ara" butonuna basmaya karsilik gelir - marka/model bagimsizdir.
    """
    subnet = subnet or _local_subnet()
    network = ipaddress.ip_network(subnet, strict=False)
    candidates = ["127.0.0.1"] + [str(ip) for ip in network.hosts()]

    open_hosts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_check_port, h, port): h for h in candidates}
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                open_hosts.append(futures[future])

    results = []
    for host in open_hosts:
        info = _verify_rosbridge(host, port)
        results.append({
            "host": host,
            "port": port,
            "verified": info.get("verified", False),
            "robot_type_guess": info.get("robot_type_guess"),
            "topic_count": len(info.get("topics", [])),
        })
    # Dogrulanmis (gercekten rosbridge olan) sonuclari one al
    results.sort(key=lambda r: not r["verified"])
    return results


if __name__ == "__main__":
    print(f"Taranan subnet: {_local_subnet()}")
    print("Ag taraniyor (bu birkac saniye surebilir)...")
    found = scan_for_robots()
    if not found:
        print("Hicbir rosbridge bulunamadi.")
    for r in found:
        tag = "[ROSBRIDGE]" if r["verified"] else "[acik port, dogrulanamadi]"
        print(f"  {tag} {r['host']}:{r['port']} - tahmini tip: {r.get('robot_type_guess')} "
              f"({r['topic_count']} topic)")
