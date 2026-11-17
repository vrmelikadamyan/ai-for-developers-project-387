from pathlib import Path
import os
import sys
import xml.etree.ElementTree as ET

mode, sha, status = sys.argv[1:]
suite = ET.parse("backend/target/surefire-reports/TEST-io.hexlet.calendar.GuestTopicProofTest.xml")
results = {}
for test in suite.findall("testcase"):
    assert test.find("error") is None and test.find("skipped") is None, test.attrib["name"]
    failure = test.find("failure")
    results[test.attrib["name"]] = failure is not None
    if failure is not None:
        print(test.attrib["name"], failure.get("message", "")[:400])

expected = {
    "publishesNormalizedTopicToGuestAndOwner": mode == "before",
    "rejectsOverlongTopicWithoutCreatingBooking": mode == "before",
    "acceptsExistingClientWithoutTopic": False,
}
assert results == expected, (results, expected)
assert (int(status) == 0) == (mode == "after"), status
lines = [f"Revision `{sha}` ({mode})", ""] + [
    f"- `{name}` — {'RED' if failed else 'GREEN'}" for name, failed in results.items()
]
report = "\n".join(lines) + "\n"
print(report)
with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
    output.write(report)
