"""Machine-readable report renderers for CI systems."""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from .models import ComparisonReport


def comparison_json(report: ComparisonReport) -> dict[str, object]:
    return report.model_dump(mode="json")


def comparison_sarif(
    report: ComparisonReport, *, artifact_path: str = "artifact.json"
) -> dict[str, object]:
    results = []
    for finding in report.findings:
        results.append(
            {
                "ruleId": finding.code,
                "level": (
                    "error"
                    if finding.severity == "error"
                    else "warning"
                    if finding.severity == "warning"
                    else "note"
                ),
                "message": {"text": finding.message},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": artifact_path}}}],
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "vouchline",
                        "informationUri": "https://github.com/Alqudimi/Vouchline",
                    }
                },
                "results": results,
            }
        ],
    }


def comparison_junit(report: ComparisonReport) -> str:
    suite = Element("testsuite", name="vouchline comparison", tests=str(len(report.findings) or 1))
    failures = sum(f.severity == "error" for f in report.findings)
    suite.set("failures", str(failures))
    if not report.findings:
        SubElement(suite, "testcase", name="comparison-passed")
    else:
        for finding in report.findings:
            case = SubElement(suite, "testcase", name=finding.code)
            if finding.severity == "error":
                failure = SubElement(case, "failure", message=finding.message)
                failure.text = finding.message
            else:
                case.set("status", finding.severity)
    return tostring(suite, encoding="unicode")
