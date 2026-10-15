import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
n = 0
for case in root.iter("testcase"):
    for bad in list(case.findall("failure")) + list(case.findall("error")):
        name = f"{case.get('classname')}::{case.get('name')}"
        text = (bad.text or bad.get("message") or "")[-3000:]
        text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title={name}::{text}")
        n += 1
print(f"{n} failures")
