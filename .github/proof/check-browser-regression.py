from pathlib import Path
import sys
from xml.etree import ElementTree
folder, exit_status = sys.argv[1:]
assert int(exit_status) != 0, "The browser check missed a visible empty topic row."
report = Path(folder) / "backend/target/surefire-reports/TEST-io.hexlet.calendar.BookingBrowserTest.xml"
cases = ElementTree.parse(report).findall("testcase")
assert len(cases) == 1
failure = cases[0].find("failure")
assert failure is not None and cases[0].find("error") is None, "Expected a failed UI assertion."
log = failure.get("message", "") + (failure.text or "")
assert "Тема разговора" in log and ("toHaveCount" in log or "toBeHidden" in log or "toBeVisible" in log), log[-2300:]
lines = [line for line in log.splitlines() if any(key in line for key in ("Тема разговора", "Expected", "Received", "toHaveCount", "toBeHidden", "toBeVisible"))]
print("Broken UI was rejected for the expected reason:")
print("\n".join(lines[:12]))
