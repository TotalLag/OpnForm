#!/usr/bin/env python3
"""Offline, fail-closed checks for the branch-scoped Nuxt AWS shadow."""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PATHS = {
    "template": "client/infra/aws/ui-shadow.yml",
    "workflow": ".github/workflows/deploy-api-direct-aws.yml",
    "bootstrap": "infra/aws/opnform-direct-aws-bootstrap.yml",
    "nuxt": "client/nuxt.config.ts",
    "package": "client/package.json",
    "sync": "client/scripts/sync-aws-public-assets.sh",
    "host": "client/lib/request-host.js",
    "packager": "client/scripts/package-aws-lambda.mjs",
    "smoke": "client/scripts/smoke-aws-lambda.mjs",
}
BREF_LAYER_VERSION_ARNS = {
    "arn:aws:lambda:us-east-1:534081306603:layer:php-83-fpm:70",
    "arn:aws:lambda:us-east-1:534081306603:layer:php-83:70",
    "arn:aws:lambda:us-east-1:534081306603:layer:console:122",
}
REGION = "us-east-1"
API_ORIGIN_PATTERN = r"^[a-z0-9]{10}\.execute-api\.us-east-1\.amazonaws\.com$"
STACK_ARN = "arn:aws:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/opnform-ui-shadow-*/*"
CHANGE_SET_ARN = "arn:aws:cloudformation:${AWS::Region}:${AWS::AccountId}:changeSet/opnform-ui-shadow-*/*"
ALARM_ARN = "arn:aws:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:opnform-ui-shadow-*"

EXECUTION_UI_STATEMENTS = {
    "ReadUiShadowArtifacts": (["s3:GetBucketLocation", "s3:ListBucket"], "UiShadowArtifactBucket.Arn"),
    "ReadUiShadowArtifactObjects": (["s3:GetObject", "s3:GetObjectVersion"], "${UiShadowArtifactBucket.Arn}/opnform-ui-shadow-*/*"),
    "ManageUiShadowPublicBuckets": (["s3:CreateBucket", "s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:GetBucketLocation", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketTagging", "s3:ListTagsForResource", "s3:PutEncryptionConfiguration", "s3:PutBucketOwnershipControls", "s3:PutBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketTagging", "s3:TagResource", "s3:UntagResource"], "arn:aws:s3:::opnform-ui-shadow-*-assets"),
    "ManageUiShadowFunctions": (["lambda:AddPermission", "lambda:CreateFunction", "lambda:CreateFunctionUrlConfig", "lambda:DeleteFunction", "lambda:DeleteFunctionUrlConfig", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig", "lambda:GetPolicy", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:UpdateFunctionUrlConfig"], "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-ui-shadow-*"),
    "ManageUiShadowLogs": (["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:ListTagsForResource", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"], "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/opnform-ui-shadow-*"),
    "ManageUiShadowLambdaRole": (["iam:CreateRole", "iam:DeleteRole", "iam:DeleteRolePolicy", "iam:GetRole", "iam:PutRolePolicy", "iam:TagRole", "iam:UntagRole"], "arn:aws:iam::${AWS::AccountId}:role/opnform-ui-shadow-*-lambda-role"),
    "PassOnlyUiShadowLambdaRole": (["iam:PassRole"], "arn:aws:iam::${AWS::AccountId}:role/opnform-ui-shadow-*-lambda-role"),
    "ManageUiShadowCloudFront": (["cloudfront:CreateCachePolicy", "cloudfront:CreateDistribution", "cloudfront:CreateDistributionWithTags", "cloudfront:CreateFunction", "cloudfront:CreateOriginAccessControl", "cloudfront:CreateOriginRequestPolicy", "cloudfront:DeleteCachePolicy", "cloudfront:DeleteDistribution", "cloudfront:DeleteFunction", "cloudfront:DeleteOriginAccessControl", "cloudfront:DeleteOriginRequestPolicy", "cloudfront:DescribeFunction", "cloudfront:GetCachePolicy", "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:GetFunction", "cloudfront:GetOriginAccessControl", "cloudfront:GetOriginRequestPolicy", "cloudfront:ListTagsForResource", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:UpdateCachePolicy", "cloudfront:UpdateDistribution", "cloudfront:UpdateFunction", "cloudfront:UpdateOriginAccessControl", "cloudfront:UpdateOriginRequestPolicy"], "*"),
    "ManageUiShadowAlarms": (["cloudwatch:DeleteAlarms", "cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource", "cloudwatch:PutMetricAlarm", "cloudwatch:TagResource", "cloudwatch:UntagResource"], ALARM_ARN),
}
UI_RESOURCE_TAGS = {
    "PublicAssetsBucket": {"Project": "OpnForm", "opnform:scope": "ui-shadow", "opnform:prefix": "ShadowPrefix"},
    "NuxtLambdaLogGroup": {"Project": "OpnForm"},
    "NuxtLambdaRole": {"Project": "OpnForm"},
    "NuxtLambda": {"Project": "OpnForm", "opnform:scope": "ui-shadow", "opnform:prefix": "ShadowPrefix"},
    "ViewerHostAndApiRewrite": {"Project": "OpnForm"},
    "Distribution": {"Project": "OpnForm", "opnform:scope": "ui-shadow", "opnform:prefix": "ShadowPrefix"},
    "LambdaErrorsAlarm": {"Project": "OpnForm"},
    "LambdaThrottlesAlarm": {"Project": "OpnForm"},
    "LambdaDurationAlarm": {"Project": "OpnForm"},
}

DEPLOY_UI_STATEMENTS = {
    "UploadUiShadowLambdaArtifacts": (["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:GetObject", "s3:ListMultipartUploadParts", "s3:PutObject"], "${UiShadowArtifactBucket.Arn}/opnform-ui-shadow-*/*"),
    "ListUiShadowArtifactBucket": (["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], "UiShadowArtifactBucket.Arn"),
    "UploadUiShadowPublicAssets": (["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:GetObject", "s3:ListMultipartUploadParts", "s3:PutObject"], "arn:aws:s3:::opnform-ui-shadow-*-assets/*"),
    "ListUiShadowPublicBuckets": (["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], "arn:aws:s3:::opnform-ui-shadow-*-assets"),
    "DeployUiShadowChangeSets": (["cloudformation:CreateChangeSet", "cloudformation:DeleteChangeSet", "cloudformation:DeleteStack", "cloudformation:DescribeChangeSet", "cloudformation:ExecuteChangeSet"], [STACK_ARN, CHANGE_SET_ARN]),
    "ReadUiShadowStacks": (["cloudformation:DescribeStackEvents", "cloudformation:DescribeStacks", "cloudformation:ListStackResources"], STACK_ARN),
    "ReadUiShadowDistribution": (["cloudfront:GetDistribution"], "*"),
}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def parse_yaml(source: str, content: str, failures: list[str]) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        data = yaml.load(content, Loader=yaml.BaseLoader)
        return data if isinstance(data, dict) else {}
    except ModuleNotFoundError:
        ruby = shutil.which("ruby")
        if ruby is None:
            failures.append(f"{source}: no YAML parser is available")
        elif subprocess.run([ruby, "-e", "require 'yaml'; YAML.parse(STDIN.read)"], input=content, text=True, capture_output=True).returncode:
            failures.append(f"{source}: invalid YAML")
    except Exception as error:
        failures.append(f"{source}: invalid YAML: {error}")
    return {}


def require_exact_ui_resource_tags(resources: Any, failures: list[str]) -> None:
    if not isinstance(resources, dict):
        failures.append("template: Resources must be a mapping")
        return

    for resource_name, expected_tags in UI_RESOURCE_TAGS.items():
        resource = resources.get(resource_name)
        if not isinstance(resource, dict):
            failures.append(f"template: missing taggable resource {resource_name}")
            continue
        if "Tags" in resource:
            failures.append(f"template: {resource_name} Tags must be under Properties")
        properties = resource.get("Properties")
        if not isinstance(properties, dict):
            failures.append(f"template: {resource_name} Properties must be a mapping")
            continue
        tags = properties.get("Tags")
        if not isinstance(tags, list):
            failures.append(f"template: {resource_name} Tags must be a list under Properties")
            continue
        tag_map: dict[Any, Any] = {}
        for tag in tags:
            if not isinstance(tag, dict) or set(tag) != {"Key", "Value"}:
                failures.append(f"template: {resource_name} tags must contain only Key and Value")
                continue
            key = tag["Key"]
            if key in tag_map:
                failures.append(f"template: {resource_name} has duplicate tag {key!r}")
            tag_map[key] = tag["Value"]
        if tag_map != expected_tags:
            failures.append(f"template: {resource_name} tags must be exactly {expected_tags}")

    for resource_name, resource in resources.items():
        if not isinstance(resource, dict):
            continue
        if "Tags" in resource:
            failures.append(f"template: {resource_name} Tags must be under Properties")
        if resource_name not in UI_RESOURCE_TAGS and isinstance(resource.get("Properties"), dict) and "Tags" in resource["Properties"]:
            failures.append(f"template: unsupported resource {resource_name} must not define Tags")


def role_statements(data: dict[str, Any], role_name: str) -> list[dict[str, Any]]:
    role = data.get("Resources", {}).get(role_name, {})
    policies = role.get("Properties", {}).get("Policies", []) if isinstance(role, dict) else []
    return [statement for policy in as_list(policies) if isinstance(policy, dict) for statement in as_list(policy.get("PolicyDocument", {}).get("Statement")) if isinstance(statement, dict)]


def ui_statements(data: dict[str, Any], role_name: str) -> list[dict[str, Any]]:
    return [statement for statement in role_statements(data, role_name) if str(statement.get("Sid", "")).startswith(("ReadUiShadow", "ManageUiShadow", "PassOnlyUiShadow", "UploadUiShadow", "ListUiShadow", "DeployUiShadow"))]


def require_exact_ui_statements(data: dict[str, Any], role_name: str, expected: dict[str, tuple[list[str], Any]], failures: list[str]) -> None:
    statements = ui_statements(data, role_name)
    found = {statement.get("Sid"): statement for statement in statements}
    if set(found) != set(expected) or len(statements) != len(expected):
        failures.append(f"bootstrap: {role_name} UI statement SIDs must be exactly {sorted(expected)}")
    for sid, (actions, resource) in expected.items():
        statement = found.get(sid)
        if not statement:
            continue
        if statement.get("Effect") != "Allow" or as_list(statement.get("Action")) != actions or statement.get("Resource") != resource:
            failures.append(f"bootstrap: {role_name} {sid} action/resource set changed")
        if sid == "PassOnlyUiShadowLambdaRole":
            expected_condition = {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}
            if statement.get("Condition") != expected_condition:
                failures.append("bootstrap: PassOnlyUiShadowLambdaRole condition changed")
        elif set(statement) != {"Sid", "Effect", "Action", "Resource"}:
            failures.append(f"bootstrap: {role_name} {sid} must not add fields")


def validate(sources: dict[str, str]) -> list[str]:
    failures: list[str] = []
    template = sources["template"]
    workflow = sources["workflow"]
    bootstrap = sources["bootstrap"]
    template_data = parse_yaml("template", template, failures)
    workflow_data = parse_yaml("workflow", workflow, failures)
    bootstrap_data = parse_yaml("bootstrap", bootstrap, failures)

    def require(source: str, value: str) -> None:
        if value not in sources[source]:
            failures.append(f"{source}: missing {value!r}")

    def forbid(source: str, pattern: str) -> None:
        if re.search(pattern, sources[source], re.I | re.M):
            failures.append(f"{source}: forbidden {pattern!r}")

    for source, content in sources.items():
        sanitized = content
        if source == "bootstrap":
            for arn in BREF_LAYER_VERSION_ARNS:
                sanitized = sanitized.replace(arn, "")
        if re.search(r"\b\d{12}\b", sanitized):
            failures.append(f"{source}: owner-style literal account IDs are forbidden")
        if re.search(r"\bopnform-(?:prod-serverless|ui-shadow-artifacts)-\d{12}-us-east-1\b", content):
            failures.append(f"{source}: literal production bucket names are forbidden")

    for value in ("Runtime: nodejs22.x", "Handler: index.handler", "MemorySize: 2048", "AuthType: AWS_IAM", "OriginAccessControlOriginType: s3", "OriginAccessControlOriginType: lambda", "SigningBehavior: always", "SigningProtocol: sigv4", "BlockPublicPolicy: true", "BlockPublicAcls: true", "RestrictPublicBuckets: true", "BucketOwnerEnforced", "Service: cloudfront.amazonaws.com", "lambda:InvokeFunctionUrl", "FunctionUrlAuthType: AWS_IAM", "InvokedViaFunctionUrl: true", "HeaderBehavior: allExcept", "CookieBehavior: all", "QueryStringBehavior: all", "DefaultTTL: 0", "MaxTTL: 0", "MinTTL: 0", "DefaultTTL: 31536000", "PathPattern: /api/_nuxt_icon/*", "PathPattern: /api/*", "PathPattern: /open/*", "PathPattern: /local/temp/*", "PathPattern: /_nuxt/*", "delete request.headers['x-opnform-viewer-host']", "delete request.headers['x-forwarded-host']", "request.uri = request.uri.slice(4)", "RetentionInDays: 14", "MetricName: Errors", "MetricName: Throttles", "MetricName: Duration", "Threshold: 20000", "PriceClass: PriceClass_100"):
        require("template", value)
    for forbidden in (r"AuthType:\s*NONE", r"WebsiteConfiguration", r"Lambda@Edge", r"Route53", r"Aliases:", r"AWS::CertificateManager", r"fly\.io|amplify|nuxt ?hub|vapor|aws blocks", r"opnform-prod", r"OriginAccessIdentity:\s*[^'\s]"):
        forbid("template", forbidden)
    for source in ("template", "workflow"):
        forbid(source, r"\b[a-z0-9]{10}\.execute-api\.us-east-1\.amazonaws\.com\b")

    resources = template_data.get("Resources", {})
    require_exact_ui_resource_tags(resources, failures)
    distribution = resources.get("Distribution", {}) if isinstance(resources, dict) else {}
    distribution_properties = distribution.get("Properties", {}) if isinstance(distribution, dict) else {}
    if not isinstance(distribution_properties, dict) or "Tags" not in distribution_properties or "Tags" in distribution:
        failures.append("template: CloudFront distribution tags must be under Properties")
    api_parameter = template_data.get("Parameters", {}).get("ApiOriginDomain", {})
    if (
        not isinstance(api_parameter, dict)
        or api_parameter.get("AllowedPattern") != API_ORIGIN_PATTERN
        or "AllowedValues" in api_parameter
    ):
        failures.append("template: ApiOriginDomain must require only a us-east-1 API Gateway execute-api domain pattern")
    shadow_prefix_parameter = template_data.get("Parameters", {}).get("ShadowPrefix", {})
    if not isinstance(shadow_prefix_parameter, dict) or shadow_prefix_parameter.get("AllowedPattern") != "^opnform-ui-shadow-[a-z0-9-]{1,12}-[a-f0-9]{12}$":
        failures.append("template: ShadowPrefix allowed pattern changed")
    lambda_artifact_parameter = template_data.get("Parameters", {}).get("LambdaArtifactKey", {})
    expected_artifact_pattern = "^opnform-ui-shadow-[a-z0-9-]{1,12}-[a-f0-9]{12}/[a-f0-9]{40}/lambda\\.zip$"
    if not isinstance(lambda_artifact_parameter, dict) or lambda_artifact_parameter.get("AllowedPattern") != expected_artifact_pattern:
        failures.append("template: LambdaArtifactKey must require a deterministic shadow, exact lowercase revision, and lambda.zip")
    lambda_code = resources.get("NuxtLambda", {}).get("Properties", {}).get("Code", {})
    if lambda_code.get("S3Key") not in ({"Ref": "LambdaArtifactKey"}, "LambdaArtifactKey"):
        failures.append("template: Nuxt Lambda code must retain the LambdaArtifactKey reference")
    lambda_environment = resources.get("NuxtLambda", {}).get("Properties", {}).get("Environment", {}).get("Variables", {})
    if lambda_environment.get("NUXT_PUBLIC_API_BASE") != "/api":
        failures.append("template: Nuxt Lambda must keep browser API requests on /api")
    if lambda_environment.get("NUXT_PRIVATE_API_BASE") != "https://${ApiOriginDomain}":
        failures.append("template: Nuxt Lambda must bind NUXT_PRIVATE_API_BASE to https://${ApiOriginDomain}")
    invoke_permission = resources.get("AllowCloudFrontInvokeFunction", {}) if isinstance(resources, dict) else {}
    if invoke_permission.get("Properties", {}).get("InvokedViaFunctionUrl") != "true":
        failures.append("template: CloudFront invoke permission must require the Function URL")
    if template.index("PathPattern: /api/_nuxt_icon/*") > template.index("PathPattern: /api/*"):
        failures.append("template: icon SSR route must precede broad API route")

    config = distribution_properties.get("DistributionConfig", {}) if isinstance(distribution_properties, dict) else {}
    cache_behaviors = config.get("CacheBehaviors", []) if isinstance(config, dict) else []
    behavior_by_path = {behavior.get("PathPattern"): behavior for behavior in cache_behaviors if isinstance(behavior, dict)}
    expected_routes = {"/api/_nuxt_icon/*": "nuxt-ssr", "/api/*": "laravel-api", "/open/*": "laravel-api", "/local/temp/*": "laravel-api", "/_nuxt/*": "private-public-assets"}
    for path, origin in expected_routes.items():
        if behavior_by_path.get(path, {}).get("TargetOriginId") != origin:
            failures.append(f"template: {path} must use {origin}")
    immutable = [path for path, behavior in behavior_by_path.items() if behavior.get("CachePolicyId") == {"Ref": "ImmutableNuxtAssetCachePolicy"} or behavior.get("CachePolicyId") == "ImmutableNuxtAssetCachePolicy"]
    if immutable != ["/_nuxt/*"]:
        failures.append("template: only /_nuxt/* may receive immutable caching")
    no_shared = resources.get("NoSharedCachePolicy", {}).get("Properties", {}).get("CachePolicyConfig", {})
    immutable_policy = resources.get("ImmutableNuxtAssetCachePolicy", {}).get("Properties", {}).get("CachePolicyConfig", {})
    if any(no_shared.get(key) != "0" for key in ("DefaultTTL", "MaxTTL", "MinTTL")):
        failures.append("template: zero-cache policy TTLs changed")
    expected_no_shared_parameters = {
        "EnableAcceptEncodingBrotli": "false",
        "EnableAcceptEncodingGzip": "false",
        "CookiesConfig": {"CookieBehavior": "none"},
        "HeadersConfig": {"HeaderBehavior": "none"},
        "QueryStringsConfig": {"QueryStringBehavior": "none"},
    }
    if no_shared.get("ParametersInCacheKeyAndForwardedToOrigin") != expected_no_shared_parameters:
        failures.append("template: zero-cache policy must disable compressed encoding and cache keys")
    expected_origin_request_policy = {
        "Name": "${ShadowPrefix}-all-viewer-no-host",
        "CookiesConfig": {"CookieBehavior": "all"},
        "HeadersConfig": {"HeaderBehavior": "allExcept", "Headers": ["host"]},
        "QueryStringsConfig": {"QueryStringBehavior": "all"},
    }
    origin_request_policy = resources.get("AllViewerOriginRequestPolicy", {}).get("Properties", {}).get("OriginRequestPolicyConfig", {})
    if origin_request_policy != expected_origin_request_policy:
        failures.append("template: origin request policy must forward all viewer values except Host")
    viewer_function = resources.get("ViewerHostAndApiRewrite", {}).get("Properties", {})
    if viewer_function.get("Name") != "${ShadowPrefix}-viewer-rewrite":
        failures.append("template: viewer function physical name changed")
    viewer_code = viewer_function.get("FunctionCode", "")
    expected_viewer_host_block = """var host = request.headers.host && request.headers.host.value;
  delete request.headers['x-opnform-viewer-host'];
  delete request.headers['x-forwarded-host'];
  if (host) {
    request.headers['x-opnform-viewer-host'] = { value: host };
    request.headers['x-forwarded-host'] = { value: host };
  }"""
    if expected_viewer_host_block not in viewer_code:
        failures.append("template: viewer function must capture Host before overwriting both trusted host headers")
    if re.search(r"delete\s+request\.headers(?:\.host|\[['\"]host['\"]\])|request\.headers(?:\.host|\[['\"]host['\"]\])\s*=", viewer_code):
        failures.append("template: viewer function must not mutate read-only Host")
    for pattern in (r"ddxn5ujwtn38g\.cloudfront\.net", r"opnform\.com", r"(?:[a-z0-9-]+\.)?lambda-url(?:\.[a-z0-9-]+)+\.on\.aws"):
        if re.search(pattern, viewer_code, re.I):
            failures.append("template: viewer function must derive trusted hosts from viewer Host")
    if len("opnform-ui-shadow-" + "a" * 12 + "-" + "f" * 12 + "-viewer-rewrite") > 64:
        failures.append("template: viewer function name exceeds CloudFront's 64-character limit")
    if immutable_policy.get("DefaultTTL") != "31536000" or immutable_policy.get("MaxTTL") != "31536000" or immutable_policy.get("MinTTL") != "86400":
        failures.append("template: immutable Nuxt cache policy TTLs changed")
    for entry in sorted(path.name for path in (ROOT / "client/public").iterdir()):
        path = f"/{entry}/*" if (ROOT / "client/public" / entry).is_dir() else f"/{entry}"
        behavior = behavior_by_path.get(path, {})
        if behavior.get("TargetOriginId") != "private-public-assets" or behavior.get("CachePolicyId") not in ({"Ref": "NoSharedCachePolicy"}, "NoSharedCachePolicy"):
            failures.append(f"template: public entry {entry} must use private S3 with zero-cache policy")

    for value in ("NITRO_PRESET=aws-lambda", "NODE_OPTIONS='--max-old-space-size=8192'", '"package:aws-lambda"', '"smoke:aws-lambda": "node scripts/smoke-aws-lambda.mjs"'):
        require("package", value)
    require("nuxt", "nitro: {preset: process.env.NITRO_PRESET}")
    for value in ("--exclude '*' --include '_nuxt/*'", "public,max-age=31536000,immutable", "no-store,private,max-age=0"):
        require("sync", value)
    require("host", "'x-opnform-viewer-host'")
    require("host", "headerValue(trustedHost) || headerValue(forwardedHost)")
    for value in ("await run('cp', ['-RP', `${server}/.`, work])", "await run('bash', ['-euo', 'pipefail'", "epoch='1980-01-01 00:00:00 UTC'", 'newline in an entry name', 'find -P "$package_root" -type l -print0', 'realpath -e -- "$entry"', 'find -P "$package_root" -mindepth 1 -exec touch -h', 'LC_ALL=C sort -z -S 64M', 'zip -X -y -q "$output" -@', "sha256sum", "bytes: archive.size", "handler: 'index.handler'"):
        require("packager", value)
    for pattern in (r"\['-RL'", r"\bcp\s+-[^\n]*L", r"find\s+-L", r"(?:\bfs\.)?cp\s*\([^)]*\bdereference\s*:\s*true", r"\bdereference\b", r"Promise\.all", r"listPackageEntries", r"\breaddir\s*\(", r"const\s+(?:entries|paths)\s*=\s*\[\]", r"\.push\(\.\.\.await", r"entries\.map", r"zip[^\n]*\.\.\.", r"(?:await\s+)?(?:execFileAsync|run)\('zip'", r"readFile\(output\)"):
        forbid("packager", pattern)
    for value in ("await execFileAsync('unzip'", "pathToFileURL(entry)", "response.statusCode >= 500", "console.log('smoke_phase=archive_extracted')", "console.log('smoke_phase=handler_imported')", "console.log('smoke_phase=handler_responded')"):
        require("smoke", value)
    if ".output" in sources["smoke"]:
        failures.append("smoke: must invoke only the extracted archive handler")

    if not isinstance(workflow_data, dict) or set(workflow_data.get("jobs", {})) != {"deploy", "shadow"}:
        failures.append("workflow: must retain API and add only the conditional shadow job")
    shadow_workflow = workflow[workflow.index("  shadow:"):] if "  shadow:" in workflow else ""
    shadow_steps = workflow_data.get("jobs", {}).get("shadow", {}).get("steps", []) if isinstance(workflow_data, dict) else []
    change_set_steps = [
        step for step in shadow_steps
        if isinstance(step, dict) and step.get("name") == "Create and execute the guarded branch UI change set"
    ]
    if len(change_set_steps) != 1:
        failures.append("workflow: UI change-set step must occur exactly once")
    else:
        change_set_run = change_set_steps[0].get("run")
        tag_arguments = re.findall(r"(?:^|\s)--tags\s+([^\s\\]+)", change_set_run if isinstance(change_set_run, str) else "")
        if tag_arguments != ["Key=Project,Value=OpnForm"]:
            failures.append("workflow: UI change set must use exactly --tags Key=Project,Value=OpnForm")
    revision_guard = '[[ "$GITHUB_SHA" =~ ^[a-f0-9]{40}$ ]]'
    artifact_derivation = 'artifact_key="${shadow}/${GITHUB_SHA}/lambda.zip"'
    artifact_output = "printf 'artifact_key=%s\\n' \"$artifact_key\" >> \"$GITHUB_OUTPUT\""
    artifact_upload = '"s3://$AWS_UI_ARTIFACT_BUCKET/${{ steps.shadow.outputs.artifact_key }}"'
    artifact_parameter = 'ParameterKey=LambdaArtifactKey,ParameterValue="$artifact_key"'
    if shadow_workflow.count(revision_guard) != 1:
        failures.append("workflow: GITHUB_SHA must be validated exactly once as 40 lowercase hexadecimal characters")
    if shadow_workflow.count(artifact_derivation) != 1 or artifact_output not in shadow_workflow:
        failures.append("workflow: must derive and publish one exact revision-keyed Lambda artifact")
    expected_upload_command = f"aws s3 cp .aws-shadow/lambda.zip \\\n            {artifact_upload} \\"
    if (
        shadow_workflow.count("aws s3 cp .aws-shadow/lambda.zip") != 1
        or shadow_workflow.count(artifact_upload) != 1
        or shadow_workflow.count(expected_upload_command) != 1
        or shadow_workflow.count("ParameterKey=LambdaArtifactKey") != 1
        or shadow_workflow.count(artifact_parameter) != 1
    ):
        failures.append("workflow: upload and LambdaArtifactKey parameter must use the same revision artifact key")
    if re.search(r'(?:\$shadow|\$\{shadow\}|steps\.shadow\.outputs\.name)/lambda\.zip', shadow_workflow):
        failures.append("workflow: static or branch-only Lambda artifact keys are forbidden")
    smoke_command = "NODE_OPTIONS='--max-old-space-size=8192' NUXT_PRIVATE_API_BASE=\"https://$AWS_API_ORIGIN_DOMAIN\" NUXT_PUBLIC_API_BASE=/api /usr/bin/time -v npm run smoke:aws-lambda 2> .aws-shadow/smoke-time.txt"
    origin_validation = '[[ "$AWS_API_ORIGIN_DOMAIN" =~ ^[a-z0-9]{10}\\.execute-api\\.us-east-1\\.amazonaws\\.com$ ]]'
    for value in ("workflow_dispatch", "target:", "options: [api, ui-shadow]", "mode:", "node-version: 22", "Maximum resident set size", smoke_command, "grep 'Maximum resident set size' .aws-shadow/smoke-time.txt | tee .aws-shadow/smoke-peak-rss.txt || true", "lambda_zip_bytes", "public_assets_bytes", "AWS_UI_ARTIFACT_BUCKET: ${{ secrets.AWS_UI_ARTIFACT_BUCKET }}", "cloudfront wait distribution-deployed", "teardown_confirmation", "test \"$shadow\" != opnform-prod", "aws s3 rm \"s3://$bucket\" --recursive", "AWS_ACCOUNT_ID: ${{ secrets.AWS_ACCOUNT_ID }}", "AWS_API_ORIGIN_DOMAIN: ${{ secrets.AWS_API_ORIGIN_DOMAIN }}", "test -n \"$AWS_API_ORIGIN_DOMAIN\"", origin_validation, "us-east-1", "--change-set-name \"$change_set\"", "--change-set-type \"$change_set_type\"", "cloudformation create-change-set", "cloudformation wait change-set-create-complete", "cloudformation execute-change-set", "cloudformation wait stack-create-complete", "cloudformation wait stack-update-complete"):
        require("workflow", value)
    if workflow.count('test -n "$AWS_API_ORIGIN_DOMAIN"') != 2 or workflow.count(origin_validation) != 2:
        failures.append("workflow: API origin secret must be non-empty and strictly validated before every use")
    for forbidden in (r"^\s*push:", r"^\s*pull_request:", r"^\s*schedule:", r"(?:inputs|github\.event\.inputs)\.api_origin_domain", r"cloudformation deploy"):
        forbid("workflow", forbidden)
    if any(value in shadow_workflow for value in ("serverless deploy", "working-directory: api", "setup-php")):
        failures.append("workflow: UI shadow job must not deploy PHP")
    rollback_status_guard = "if status=\"$(aws cloudformation describe-stacks --stack-name \"$shadow\" --region us-east-1 --query 'Stacks[0].StackStatus' --output text 2>/dev/null)\"; then"
    rollback_complete_guard = 'if test "$status" = ROLLBACK_COMPLETE; then'
    rollback_event_query = "--query 'StackEvents[?contains(ResourceStatus, `FAILED`) || contains(ResourceStatus, `ROLLBACK`)].[LogicalResourceId,ResourceType,ResourceStatus,ResourceStatusReason] | [0:20]'"
    rollback_event_command = "              aws cloudformation describe-stack-events \\\n"
    for value in ("Fail closed on a rolled-back branch shadow", rollback_status_guard, rollback_complete_guard, rollback_event_command, rollback_event_query, "--output table"):
        require("workflow", value)
    if rollback_status_guard in shadow_workflow and shadow_workflow.index(rollback_status_guard) > shadow_workflow.index("      - name: Set up Node.js 22"):
        failures.append("workflow: rollback diagnostic must run before Node setup")
    if Path(ROOT / ".github/workflows/deploy-ui-shadow-aws.yml").exists():
        failures.append("workflow: standalone UI shadow workflow must be removed")

    require_exact_ui_statements(bootstrap_data, "OpnFormCloudFormationExecutionRole", EXECUTION_UI_STATEMENTS, failures)
    require_exact_ui_statements(bootstrap_data, "OpnFormGitHubDeployRole", DEPLOY_UI_STATEMENTS, failures)
    expected_ui_sids = set(EXECUTION_UI_STATEMENTS) | set(DEPLOY_UI_STATEMENTS)
    for role in ("OpnFormCloudFormationExecutionRole", "OpnFormGitHubDeployRole"):
        for statement in role_statements(bootstrap_data, role):
            resources = " ".join(str(resource) for resource in as_list(statement.get("Resource")))
            if "opnform-ui-shadow" in resources and statement.get("Sid") not in expected_ui_sids:
                failures.append(f"bootstrap: {role} has an unapproved UI-shadow grant")
    for forbidden in (r"route53:",):
        forbid("bootstrap", forbidden)

    return failures


def expect_rejected(sources: dict[str, str], source: str, old: str, new: str) -> str | None:
    mutated = dict(sources)
    if old not in mutated[source]:
        return f"negative fixture cannot find {old!r} in {source}"
    mutated[source] = mutated[source].replace(old, new, 1)
    if not validate(mutated):
        return f"negative mutation was accepted: {source} {new!r}"
    return None


def packager_fixture_failures() -> list[str]:
    node = shutil.which("node")
    unzip = shutil.which("unzip")
    if node is None or unzip is None:
        return ["packager fixture: node and unzip are required"]

    with tempfile.TemporaryDirectory(prefix="opnform-package-fixture-") as temporary:
        fixture = Path(temporary)
        server = fixture / ".output/server"
        dependency_dir = server / ".nitro/dependencies"
        dependency_dir.mkdir(parents=True)
        payload = dependency_dir / "payload.mjs"
        payload.write_text("export const payload = 'materialized';\n")
        node_modules = server / "node_modules"
        node_modules.mkdir()
        dependency = node_modules / "dependency.mjs"
        dependency.symlink_to("../.nitro/dependencies/payload.mjs")
        linked_dependencies = server / "linked-dependencies"
        linked_dependencies.symlink_to(".nitro/dependencies", target_is_directory=True)
        (server / "index.mjs").write_text(
            "import { payload } from './node_modules/dependency.mjs';\n"
            "export async function handler() { return { statusCode: 200, body: payload } }\n"
        )

        command = [node, str(ROOT / PATHS["packager"])]
        first = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if first.returncode:
            return [f"packager fixture: first package failed: {first.stderr.strip() or first.stdout.strip()}"]

        archive = fixture / ".aws-shadow/lambda.zip"
        package = fixture / ".aws-shadow/package"
        first_bytes = archive.read_bytes()
        packaged_dependency = package / "node_modules/dependency.mjs"
        if not packaged_dependency.is_symlink() or packaged_dependency.readlink() != Path("../.nitro/dependencies/payload.mjs"):
            return ["packager fixture: safe relative symbolic link was not preserved"]

        second = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if second.returncode:
            return [f"packager fixture: second package failed: {second.stderr.strip() or second.stdout.strip()}"]
        if archive.read_bytes() != first_bytes:
            return ["packager fixture: repeated package output is not deterministic"]

        with zipfile.ZipFile(archive) as zipped:
            entry = zipped.getinfo("node_modules/dependency.mjs")
            directory_link = zipped.getinfo("linked-dependencies")
            if not stat.S_ISLNK(entry.external_attr >> 16) or zipped.read(entry) != b"../.nitro/dependencies/payload.mjs":
                return ["packager fixture: archive did not retain the safe relative symbolic link"]
            if not stat.S_ISLNK(directory_link.external_attr >> 16) or zipped.read(directory_link) != b".nitro/dependencies":
                return ["packager fixture: archive did not retain the safe directory symbolic link"]
            if "linked-dependencies/payload.mjs" in zipped.namelist():
                return ["packager fixture: packager followed a directory symbolic link"]

        extracted = fixture / "extracted"
        extraction = subprocess.run([unzip, "-q", str(archive), "-d", str(extracted)], text=True, capture_output=True, check=False)
        if extraction.returncode:
            return [f"packager fixture: archive extraction failed: {extraction.stderr.strip() or extraction.stdout.strip()}"]
        extracted_dependency = extracted / "node_modules/dependency.mjs"
        if not extracted_dependency.is_symlink() or extracted_dependency.resolve() != (extracted / ".nitro/dependencies/payload.mjs").resolve():
            return ["packager fixture: extracted dependency link does not resolve inside the package"]
        handler = subprocess.run([node, "--input-type=module", "-e", "import { handler } from './index.mjs'; const response = await handler(); if (response.body !== 'materialized') process.exit(1)"], cwd=extracted, text=True, capture_output=True, check=False)
        if handler.returncode:
            return [f"packager fixture: extracted handler did not resolve its dependency link: {handler.stderr.strip() or handler.stdout.strip()}"]

        newline = server / "newline\nentry.mjs"
        newline.write_text("export const newline = true;\n")
        rejected_newline = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if rejected_newline.returncode == 0 or "newline in an entry name" not in rejected_newline.stderr:
            return ["packager fixture: newline entry mutation was accepted"]
        newline.unlink()

        absolute = server / "absolute-link.mjs"
        absolute.symlink_to(payload.resolve())
        rejected_absolute = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if rejected_absolute.returncode == 0 or "absolute symbolic link" not in rejected_absolute.stderr:
            return ["packager fixture: absolute symbolic link mutation was accepted"]
        absolute.unlink()

        outside = fixture / ".aws-shadow/outside.mjs"
        outside.write_text("export const outside = true;\n")
        escaping = server / "escaping-link.mjs"
        escaping.symlink_to("../../.aws-shadow/outside.mjs")
        rejected_escaping = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if rejected_escaping.returncode == 0 or "outside the package" not in rejected_escaping.stderr:
            return ["packager fixture: escaping symbolic link mutation was accepted"]
        escaping.unlink()

        missing = server / "missing-link.mjs"
        missing.symlink_to("missing-target.mjs")
        rejected_missing = subprocess.run(command, cwd=fixture, text=True, capture_output=True, check=False)
        if rejected_missing.returncode == 0 or "missing symbolic link target" not in rejected_missing.stderr:
            return ["packager fixture: missing symbolic link mutation was accepted"]
    return []


def route_fixture_failures() -> list[str]:
    def viewer_request(request: dict[str, Any]) -> dict[str, Any]:
        result = {**request, "headers": dict(request["headers"])}
        host = result["headers"].get("host")
        result["headers"].pop("x-opnform-viewer-host", None)
        result["headers"].pop("x-forwarded-host", None)
        if host:
            result["headers"]["x-opnform-viewer-host"] = host
            result["headers"]["x-forwarded-host"] = host
        if result["uri"].startswith("/api/") and not result["uri"].startswith("/api/_nuxt_icon/"):
            result["uri"] = result["uri"][4:]
        return result

    request = {"uri": "/api/open/forms", "method": "POST", "querystring": "x=1", "body": "{}", "headers": {"host": "shadow.example.test", "authorization": "Bearer test", "cookie": "session=test", "content-type": "application/json", "form-password": "test", "x-opnform-viewer-host": "spoof.test", "x-forwarded-host": "spoof.test"}}
    rewritten = viewer_request(request)
    failures = []
    if rewritten["uri"] != "/open/forms":
        failures.append("route fixture: /api prefix must be stripped exactly once")
    for key in ("method", "querystring", "body"):
        if rewritten[key] != request[key]:
            failures.append(f"route fixture: {key} must be preserved")
    for header in ("authorization", "cookie", "content-type", "form-password"):
        if rewritten["headers"].get(header) != request["headers"][header]:
            failures.append(f"route fixture: {header} must be forwarded")
    if rewritten["headers"].get("x-opnform-viewer-host") != "shadow.example.test":
        failures.append("route fixture: viewer host must overwrite a spoofed header")
    if rewritten["headers"].get("x-forwarded-host") != "shadow.example.test":
        failures.append("route fixture: forwarded host must overwrite a spoofed header")
    if viewer_request({"uri": "/api/_nuxt_icon/x", "headers": {"host": "a"}})["uri"] != "/api/_nuxt_icon/x":
        failures.append("route fixture: Nuxt icon route must not be rewritten")
    return failures


def self_test(sources: dict[str, str]) -> list[str]:
    cases = [
        ("bootstrap", "s3:PutEncryptionConfiguration", "s3:PutBucketEncryption"),
        ("bootstrap", "s3:PutEncryptionConfiguration", "s3:*"),
        ("bootstrap", "s3:GetBucketTagging", "s3:GetBucketAcl"),
        ("bootstrap", "Sid: ManageUiShadowLogs\n                Effect: Allow\n                Action:\n                  - logs:CreateLogGroup\n                  - logs:DeleteLogGroup\n                  - logs:ListTagsForResource", "Sid: ManageUiShadowLogs\n                Effect: Allow\n                Action:\n                  - logs:CreateLogGroup\n                  - logs:DeleteLogGroup\n                  - logs:ListTagsForLogGroup"),
        ("bootstrap", "cloudwatch:ListTagsForResource", "cloudwatch:ListTagsForAlarm"),
        ("bootstrap", "cloudfront:ListTagsForResource\n", ""),
        ("bootstrap", "Resource: arn:aws:s3:::opnform-ui-shadow-*-assets", "Resource: arn:aws:s3:::opnform-ui-shadow-*"),
        ("bootstrap", "Sid: ReadUiShadowArtifacts\n                Effect: Allow\n                Action:\n                  - s3:GetBucketLocation\n                  - s3:ListBucket", "Sid: ReadUiShadowArtifacts\n                Effect: Allow\n                Action:\n                  - s3:GetBucketLocation\n                  - s3:ListBucket\n                  - ec2:RunInstances"),
        ("bootstrap", "Resource: !Sub 'arn:aws:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:opnform-ui-shadow-*'", "Resource:\n                  - !Sub 'arn:aws:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:opnform-ui-shadow-*'\n                  - !Sub 'arn:aws:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:unrelated'"),
        ("bootstrap", "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-ui-shadow-*", "arn:aws:lambda:${AWS::Region}:*:function:opnform-ui-shadow-*"),
        ("bootstrap", "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-ui-shadow-*", "arn:aws:lambda:us-*-1:${AWS::AccountId}:function:opnform-ui-shadow-*"),
        ("template", "Key: Project\n          Value: OpnForm", "Key: CostCenter\n          Value: OpnForm"),
        ("template", "Key: Project\n          Value: OpnForm", "Key: Project\n          Value: Other"),
        ("template", "    Type: AWS::CloudFront::OriginAccessControl\n    Properties:", "    Type: AWS::CloudFront::OriginAccessControl\n    Properties:\n      Tags:\n        - Key: Project\n          Value: OpnForm"),
        ("template", "Service: cloudfront.amazonaws.com", "Principal: '*'"),
        ("template", "AuthType: AWS_IAM", "AuthType: NONE"),
        ("template", "BucketOwnerEnforced", "WebsiteConfiguration"),
        ("template", "^[a-z0-9]{10}\\.execute-api\\.us-east-1\\.amazonaws\\.com$", ".*"),
        ("template", "NUXT_PRIVATE_API_BASE: !Sub 'https://${ApiOriginDomain}'", "NUXT_PRIVATE_API_BASE: https://example.com"),
        ("template", "No-DNS Nuxt UI shadow", "opnform-prod"),
        ("template", "cloudfront-js-2.0", "Lambda@Edge"),
        ("template", "PriceClass: PriceClass_100", "Route53"),
        ("template", "PathPattern: /api/_nuxt_icon/*\n            TargetOriginId: nuxt-ssr", "PathPattern: /api/_nuxt_icon/*\n            TargetOriginId: laravel-api"),
        ("template", "DefaultTTL: 0", "DefaultTTL: 3600"),
        ("template", "DefaultTTL: 31536000", "DefaultTTL: 0"),
        ("template", "MemorySize: 2048", "MemorySize: 4096"),
        ("template", "EnableAcceptEncodingGzip: false", "EnableAcceptEncodingGzip: true"),
        ("template", "HeaderBehavior: allExcept", "HeaderBehavior: allViewerExceptHostHeader"),
        ("template", "            - host", "            - authorization"),
        ("template", "${ShadowPrefix}-viewer-rewrite", "${ShadowPrefix}-viewer-host-and-api-rewrite"),
        ("template", "delete request.headers['x-forwarded-host'];", ""),
        ("template", "request.headers['x-forwarded-host'] = { value: host };", ""),
        ("template", "request.headers['x-forwarded-host'] = { value: host };", "request.headers['x-forwarded-host'] = { value: 'spoof.test' };"),
        ("template", "{1,12}", "{1,99}"),
        ("template", "/[a-f0-9]{40}/lambda\\.zip$", "/[a-f0-9]{7}/lambda\\.zip$"),
        ("template", "/[a-f0-9]{40}/lambda\\.zip$", "/[a-z0-9._/-]+\\.zip$"),
        ("template", "S3Key: !Ref LambdaArtifactKey", "S3Key: lambda.zip"),
        ("packager", "['-RP'", "['-R'"),
        ("packager", "const packageScript = String.raw`", "const paths = []\nconst packageScript = String.raw`"),
        ("packager", "const packageScript = String.raw`", "const zipArguments = ['zip', ...entries.map(({ path }) => path)]\nconst packageScript = String.raw`"),
        ("packager", "find -P \"$package_root\" -type l -print0", "find \"$package_root\" -type l -print0"),
        ("packager", "realpath -e -- \"$entry\"", "true # skipped symlink resolution"),
        ("packager", "epoch='1980-01-01 00:00:00 UTC'", "epoch='1981-01-01 00:00:00 UTC'"),
        ("packager", "touch -h -d \"$epoch\"", "touch -d \"$epoch\""),
        ("packager", "LC_ALL=C sort -z -S 64M", "sort -z"),
        ("packager", "zip -X -y -q \"$output\" -@", "zip -X -q \"$output\" -@"),
        ("packager", "await run('bash', ['-euo', 'pipefail'", "await Promise.all([])"),
        ("packager", "await run('cp', ['-RP', `${server}/.`, work])", "await fs.cp(server, work, { dereference: true, recursive: true })"),
        ("smoke", "response.statusCode >= 500", "response.statusCode >= 501"),
        ("smoke", "console.log('smoke_phase=archive_extracted')", "console.log('smoke_phase=archive_ready')"),
        ("smoke", "console.log('smoke_phase=handler_imported')", "console.log('smoke_phase=handler_ready')"),
        ("smoke", "console.log('smoke_phase=handler_responded')", "console.log('smoke_phase=response_ready')"),
        ("workflow", "--tags Key=Project,Value=OpnForm \\\n", ""),
        ("workflow", "--tags Key=Project,Value=OpnForm", "--tags Key=Project,Value=Other"),
        ("workflow", "NODE_OPTIONS='--max-old-space-size=8192' NUXT_PRIVATE_API_BASE=\"https://$AWS_API_ORIGIN_DOMAIN\" NUXT_PUBLIC_API_BASE=/api /usr/bin/time -v npm run smoke:aws-lambda 2> .aws-shadow/smoke-time.txt", "NODE_OPTIONS='--max-old-space-size=16384' NUXT_PRIVATE_API_BASE=\"https://$AWS_API_ORIGIN_DOMAIN\" NUXT_PUBLIC_API_BASE=/api /usr/bin/time -v npm run smoke:aws-lambda 2> .aws-shadow/smoke-time.txt"),
        ("workflow", "AWS_API_ORIGIN_DOMAIN: ${{ secrets.AWS_API_ORIGIN_DOMAIN }}", ""),
        ("workflow", "NUXT_PRIVATE_API_BASE=\"https://$AWS_API_ORIGIN_DOMAIN\" ", ""),
        ("workflow", '[[ "$AWS_API_ORIGIN_DOMAIN" =~ ^[a-z0-9]{10}\\.execute-api\\.us-east-1\\.amazonaws\\.com$ ]]', '[[ "$AWS_API_ORIGIN_DOMAIN" =~ ^[a-z0-9]{1,63}\\.execute-api\\.us-east-1\\.amazonaws\\.com$ ]]'),
        ("workflow", "NUXT_PUBLIC_API_BASE=/api ", ""),
        ("workflow", "/usr/bin/time -v npm run smoke:aws-lambda", "/usr/bin/time npm run smoke:aws-lambda"),
        ("workflow", ".aws-shadow/smoke-peak-rss.txt", ".aws-shadow/peak-rss.txt"),
        ("workflow", '[[ "$GITHUB_SHA" =~ ^[a-f0-9]{40}$ ]]', '[[ "$GITHUB_SHA" =~ ^[a-f0-9]{7}$ ]]'),
        ("workflow", '[[ "$GITHUB_SHA" =~ ^[a-f0-9]{40}$ ]]', 'test -n "$GITHUB_SHA"'),
        ("workflow", 'artifact_key="${shadow}/${GITHUB_SHA}/lambda.zip"', 'artifact_key="${shadow}/lambda.zip"'),
        ("workflow", 'artifact_key="${shadow}/${GITHUB_SHA}/lambda.zip"', 'artifact_key="${shadow}/${GITHUB_REF_NAME}/lambda.zip"'),
        ("workflow", '${{ steps.shadow.outputs.artifact_key }}', '${{ steps.shadow.outputs.name }}/lambda.zip'),
        ("workflow", 'aws s3 cp .aws-shadow/lambda.zip', 'aws s3 cp .aws-shadow/arbitrary.zip'),
        ("workflow", 'ParameterKey=LambdaArtifactKey,ParameterValue="$artifact_key"', 'ParameterKey=LambdaArtifactKey,ParameterValue="$shadow/lambda.zip"'),
        ("workflow", 'ParameterKey=LambdaArtifactKey,ParameterValue="$artifact_key"', 'ParameterKey=LambdaArtifactKey,ParameterValue="arbitrary/path.zip"'),
        ("workflow", 'if test "$status" = ROLLBACK_COMPLETE; then', 'if test "$status" = CREATE_FAILED; then'),
        ("workflow", "              aws cloudformation describe-stack-events \\\n", "              aws cloudformation describe-stacks \\\n"),
        ("workflow", " | [0:20]'", " | [0:21]'"),
    ]
    failures = packager_fixture_failures() + route_fixture_failures() + [failure for case in cases if (failure := expect_rejected(sources, *case))]
    moved = dict(sources)
    moved["bootstrap"] = moved["bootstrap"].replace("OpnFormCloudFormationExecutionRole:", "OpnFormCloudFormationExecutionRoleDisabled:", 1).replace("OpnFormGitHubDeployRole:", "OpnFormCloudFormationExecutionRole:", 1)
    if not validate(moved):
        failures.append("negative mutation was accepted: UI grants moved to deploy role")
    return failures


def load_sources() -> dict[str, str]:
    return {name: (ROOT / path).read_text() for name, path in PATHS.items()}


sources = load_sources()
failures = validate(sources)
if "--self-test" in sys.argv:
    failures.extend(self_test(sources))
if failures:
    print("UI shadow deployment boundary violations:")
    print("\n".join(f"- {failure}" for failure in failures))
    raise SystemExit(1)
print("UI shadow deployment boundaries passed")
