"""One small, explicit AWS invocation; never runs candidate code."""
import argparse
import json
import os
import uuid
from pathlib import Path

import boto3
from botocore.config import Config


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--allow-aws", action="store_true")
    p.add_argument("--model-id", default=os.getenv("BEDROCK_MODEL_ID"))
    p.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    a = p.parse_args()
    if not a.allow_aws or not a.model_id:
        p.error("Requires --allow-aws and BEDROCK_MODEL_ID")
    out = Path("runs") / ("bedrock-smoke-" + uuid.uuid4().hex)
    out.mkdir(parents=True)
    evidence = {"model": a.model_id, "region": a.region, "status": "STARTED"}
    try:
        session = boto3.Session(profile_name=a.profile, region_name=a.region)
        config = Config(connect_timeout=10, read_timeout=60, retries={"total_max_attempts": 1})
        session.client("sts", config=config).get_caller_identity()
        response = session.client("bedrock-runtime", config=config).converse(
            modelId=a.model_id, messages=[{"role":"user", "content":[{"text":"Reply with OK only."}]}],
            inferenceConfig={"maxTokens":32})
        evidence.update(status="COMPLETED", usage=response.get("usage"), output=response["output"],
                        request_id=response.get("ResponseMetadata", {}).get("RequestId"))
    except Exception as error:
        evidence.update(status="ERROR", error_type=type(error).__name__, error=str(error))
    (out / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence": str(out)}))
    return 0 if evidence["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
