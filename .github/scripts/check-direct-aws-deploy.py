#!/usr/bin/env python3
"""Check direct-AWS deployment invariants without contacting AWS."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
failures: list[str] = []


def text(path: str) -> str:
    return (ROOT / path).read_text()


def parse_yaml(path: str):
    """Parse YAML for syntax; use PyYAML when available, Ruby's stdlib otherwise."""
    content = text(path)
    try:
        import yaml  # type: ignore

        return yaml.load(content, Loader=yaml.BaseLoader)
    except ModuleNotFoundError:
        ruby = shutil.which("ruby")
        if ruby is None:
            failures.append(f"{path}: no YAML parser is available")
            return {}
        result = subprocess.run(
            [ruby, "-e", "require 'yaml'; YAML.parse(STDIN.read)"],
            input=content,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            failures.append(f"{path}: invalid YAML: {result.stderr.strip()}")
        return {}
    except Exception as error:
        failures.append(f"{path}: invalid YAML: {error}")
        return {}


def require(content: str, needle: str, label: str) -> None:
    if needle not in content:
        failures.append(f"{label}: missing {needle!r}")


def forbid(content: str, pattern: str, label: str) -> None:
    if re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
        failures.append(f"{label}: forbidden {pattern!r}")


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def role_statements(template_data, role_name: str):
    if not isinstance(template_data, dict):
        return []
    role = template_data.get("Resources", {}).get(role_name)
    statements = []
    for policy in role.get("Properties", {}).get("Policies", []) if isinstance(role, dict) else []:
        statements.extend(as_list(policy.get("PolicyDocument", {}).get("Statement")))
    return [statement for statement in statements if isinstance(statement, dict)]


def iam_role_policy_statements(template_data):
    if not isinstance(template_data, dict):
        return []
    resources = template_data.get("Resources", {})
    if not isinstance(resources, dict):
        return []

    statements = []
    for role_name, role in resources.items():
        if not isinstance(role, dict) or role.get("Type") != "AWS::IAM::Role":
            continue
        for policy in as_list(role.get("Properties", {}).get("Policies")):
            if not isinstance(policy, dict):
                continue
            for statement in as_list(policy.get("PolicyDocument", {}).get("Statement")):
                if isinstance(statement, dict):
                    statements.append((role_name, policy.get("PolicyName"), statement))
    return statements


serverless = text("api/serverless.yml")
workflow = text(".github/workflows/deploy-api-direct-aws.yml")
template = text("infra/aws/opnform-direct-aws-bootstrap.yml")
package = json.loads(text("api/package.json"))
lock = json.loads(text("api/package-lock.json"))
serverless_data = parse_yaml("api/serverless.yml")
workflow_data = parse_yaml(".github/workflows/deploy-api-direct-aws.yml")
template_data = parse_yaml("infra/aws/opnform-direct-aws-bootstrap.yml")

tracked_files = subprocess.run(
    ["git", "ls-files", "-z"],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.rstrip("\0").split("\0")
private_runbooks = {
    "docs/deployment/direct-aws-production.mdx",
    "client/infra/aws/UI_SHADOW_RUNBOOK.md",
}
for path in sorted(private_runbooks):
    if (ROOT / path).exists():
        failures.append(f"{path}: private deployment runbook must not exist publicly")

deployed_api_hostname = re.compile(r"(?<![a-z0-9{])\b[a-z0-9]{10}\.execute-api\.us-east-1\.amazonaws\.com\b")
for path in tracked_files:
    try:
        content = (ROOT / path).read_text(errors="ignore")
    except OSError:
        continue
    if deployed_api_hostname.search(content):
        failures.append(f"{path}: literal deployed API Gateway hostname is forbidden")

if isinstance(serverless_data, dict) and "bref" in serverless_data:
    failures.append("serverless configuration: Bref Cloud ownership is forbidden")
for needle in (
    "service: opnform-api",
    "stage: prod",
    "stackName: opnform-prod",
    "deploymentMethod: changesets",
    "region: us-east-1",
    "name: ${env:AWS_API_DEPLOYMENT_BUCKET}",
    "deploymentRole: ${env:AWS_CFN_ROLE_ARN}",
    "ssmPrefix: /opnform/prod",
    "arn:aws:ssm:${aws:region}:${aws:accountId}:parameter/opnform/prod/*",
    "Action: ssm:GetParameters",
    "maxConcurrency: 4",
    "rate: rate(1 minute)",
    "name: opnform-prod-jobs-worker",
):
    require(serverless, needle, "serverless configuration")
forbid(serverless, r"/laravel/", "serverless configuration")
if isinstance(serverless_data, dict):
    if serverless_data.get("provider", {}).get("stackName") != "opnform-prod":
        failures.append("serverless configuration: stackName must be opnform-prod")
    if serverless_data.get("params", {}).get("default", {}).get("ssmPrefix") != "/opnform/prod":
        failures.append("serverless configuration: ssmPrefix must be /opnform/prod")
forbid(serverless, r"\bus-(?!east-1\b)[a-z]+-\d+\b", "serverless configuration")

if package.get("devDependencies", {}).get("serverless") != "3.40.0":
    failures.append("api/package.json: serverless must be the exact 3.40.0 dev dependency")
if lock.get("lockfileVersion") != 3:
    failures.append("api/package-lock.json: lockfileVersion must remain 3")
if lock.get("packages", {}).get("", {}).get("devDependencies", {}).get("serverless") != "3.40.0":
    failures.append("api/package-lock.json: root serverless dependency is not locked")
if lock.get("packages", {}).get("node_modules/serverless", {}).get("version") != "3.40.0":
    failures.append("api/package-lock.json: serverless 3.40.0 package entry is missing")

if isinstance(workflow_data, dict):
    triggers = workflow_data.get("on")
    if not isinstance(triggers, dict) or set(triggers) != {"workflow_dispatch"}:
        failures.append("deployment workflow: on must contain only workflow_dispatch")
    dispatch_inputs = triggers.get("workflow_dispatch", {}).get("inputs", {})
    target = dispatch_inputs.get("target", {}) if isinstance(dispatch_inputs, dict) else {}
    jobs = workflow_data.get("jobs", {})
    api_job = jobs.get("deploy", {}) if isinstance(jobs, dict) else {}
    shadow_job = jobs.get("shadow", {}) if isinstance(jobs, dict) else {}
    if target.get("default") != "api" or target.get("type") != "choice" or target.get("options") != ["api", "ui-shadow"]:
        failures.append("deployment workflow: target must default to the API with ui-shadow as the only alternative")
    if api_job.get("if") != "inputs.target != 'ui-shadow'":
        failures.append("deployment workflow: default API job must be skipped only for ui-shadow")
    if shadow_job.get("if") != "inputs.target == 'ui-shadow'":
        failures.append("deployment workflow: UI shadow job must be separately conditional")
else:
    failures.append("deployment workflow: YAML root must be a mapping")
for trigger in ("push", "schedule", "pull_request", "workflow_run", "workflow_call"):
    forbid(workflow, rf"^\s*{trigger}:", "deployment workflow")
for needle in (
    "environment: opnform-prod",
    "id-token: write",
    "contents: read",
    "aws-actions/configure-aws-credentials@v4",
    "role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}",
    "AWS_API_DEPLOYMENT_BUCKET: ${{ secrets.AWS_API_DEPLOYMENT_BUCKET }}",
    "AWS_CFN_ROLE_ARN: ${{ secrets.AWS_CFN_ROLE_ARN }}",
    "AWS_ACCOUNT_ID: ${{ secrets.AWS_ACCOUNT_ID }}",
    "shivammathur/setup-php@v2",
    '"us-east-1"',
    '"/opnform/prod/$name"',
    '"SecureString"',
    'npx serverless bref:cli --stage prod --region us-east-1 --args="migrate:status --no-interaction"',
    'npx serverless bref:cli --stage prod --region us-east-1 --args="migrate --force --no-interaction"',
    'grep -F "Nothing to migrate." /tmp/opnform-migrate-verify.log',
    "npx serverless deploy --stage prod --region us-east-1",
):
    require(workflow, needle, "deployment workflow")
ssm_parameter_names = (
    "APP_URL FRONT_URL AWS_BUCKET AWS_ENDPOINT AWS_URL "
    "MAIL_FROM_ADDRESS MAIL_FROM_NAME APP_KEY DATABASE_URL JWT_SECRET"
)
ssm_type_checks = re.findall(
    r"for name in ([A-Z0-9_ ]+); do\s*\n"
    r"\s*test \"\$\(aws ssm get-parameter --name \"/opnform/prod/\$name\" "
    r"--query 'Parameter\.Type' --output text\)\" = \"([^\"]+)\"\s*\n"
    r"\s*done",
    workflow,
)
if ssm_type_checks != [(ssm_parameter_names, "SecureString")]:
    failures.append(
        "deployment workflow: all ten SSM parameters must be checked once as SecureString"
    )
forbid(workflow, r"Parameter\.Type.*=\s*\"String\"", "deployment workflow")
forbid(workflow, r"role-to-assume:\s*arn:aws:iam::\d{12}", "deployment workflow")

for needle in (
    "https://token.actions.githubusercontent.com",
    "sts.amazonaws.com",
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "cabd2a79a1076a31f21d253635cb039d4329a5e8",
    "repo:TotalLag@1744428/OpnForm@1317796294:environment:opnform-prod",
    "ServerlessArtifactBucketName:",
    "UiShadowArtifactBucketName:",
    "BucketName: !Ref ServerlessArtifactBucketName",
    "BucketName: !Ref UiShadowArtifactBucketName",
    "VersioningConfiguration:",
    "PublicAccessBlockConfiguration:",
    "OpnFormCloudFormationExecutionRole",
    "OpnFormGitHubDeployRole",
    "iam:PassedToService: cloudformation.amazonaws.com",
    "changeSet/opnform-prod-change-set/*",
    "cloudformation:DeleteChangeSet",
    "InvokeOnlyProductionArtisan",
    "lambda:InvokeFunction",
    "function:opnform-prod-artisan",
    "sqs:CreateQueue",
    "logs:CreateLogGroup",
    "iam:CreateRole",
):
    require(template, needle, "bootstrap template")
execution_statements = role_statements(template_data, "OpnFormCloudFormationExecutionRole")
deploy_statements = role_statements(template_data, "OpnFormGitHubDeployRole")
all_iam_role_policy_statements = iam_role_policy_statements(template_data)
if not execution_statements:
    failures.append("bootstrap template: CloudFormation execution role policy statements are missing")
if not deploy_statements:
    failures.append("bootstrap template: GitHub deploy role policy statements are missing")

artisan_invoke_statements = [
    statement for statement in deploy_statements
    if statement.get("Sid") == "InvokeOnlyProductionArtisan"
]
expected_artisan_arn = "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-prod-artisan"
if len(artisan_invoke_statements) != 1:
    failures.append("bootstrap template: exactly one InvokeOnlyProductionArtisan statement is required")
else:
    artisan_invoke = artisan_invoke_statements[0]
    if as_list(artisan_invoke.get("Action")) != ["lambda:InvokeFunction"]:
        failures.append("bootstrap template: artisan invocation must grant only lambda:InvokeFunction")
    if artisan_invoke.get("Resource") != expected_artisan_arn:
        failures.append("bootstrap template: artisan invocation must target only opnform-prod-artisan")
for statement in deploy_statements:
    invoke_actions = [
        action for action in as_list(statement.get("Action"))
        if action == "lambda:InvokeFunction"
    ]
    if invoke_actions and statement.get("Sid") != "InvokeOnlyProductionArtisan":
        failures.append("bootstrap template: lambda invocation must stay in InvokeOnlyProductionArtisan")

event_source_mapping_resource = "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:event-source-mapping:*"
event_source_mapping_actions_expected = [
    "lambda:CreateEventSourceMapping",
    "lambda:TagResource",
]
event_source_mapping_statements = [
    (role_name, policy_name, statement)
    for role_name, policy_name, statement in all_iam_role_policy_statements
    if statement.get("Sid") == "CreateProductionEventSourceMappings"
]
if len(event_source_mapping_statements) != 1:
    failures.append(
        "bootstrap template: CreateProductionEventSourceMappings must occur exactly once"
    )
else:
    role_name, policy_name, statement = event_source_mapping_statements[0]
    if (
        role_name != "OpnFormCloudFormationExecutionRole"
        or policy_name != "OpnFormProductionStack"
    ):
        failures.append(
            "bootstrap template: CreateProductionEventSourceMappings must stay in the CloudFormation execution role policy"
        )
    if statement.get("Effect") != "Allow":
        failures.append("bootstrap template: CreateProductionEventSourceMappings effect must be Allow")
    actions = statement.get("Action")
    if (
        not isinstance(actions, list)
        or actions != event_source_mapping_actions_expected
        or len(actions) != len(set(actions))
    ):
        failures.append(
            "bootstrap template: CreateProductionEventSourceMappings must list exactly lambda:CreateEventSourceMapping and lambda:TagResource"
        )
    if statement.get("Resource") != event_source_mapping_resource:
        failures.append(
            "bootstrap template: CreateProductionEventSourceMappings must use the exact regional event-source-mapping ARN"
        )
    if set(statement) != {"Sid", "Effect", "Action", "Resource"}:
        failures.append(
            "bootstrap template: CreateProductionEventSourceMappings must not add conditions or other fields"
        )

event_source_mapping_actions = [
    (role_name, policy_name, statement)
    for role_name, policy_name, statement in all_iam_role_policy_statements
    if "lambda:CreateEventSourceMapping" in as_list(statement.get("Action"))
]
if len(event_source_mapping_actions) != 1:
    failures.append(
        "bootstrap template: lambda:CreateEventSourceMapping must occur only in CreateProductionEventSourceMappings"
    )
elif (
    event_source_mapping_actions[0][:2]
    != ("OpnFormCloudFormationExecutionRole", "OpnFormProductionStack")
    or event_source_mapping_actions[0][2].get("Sid")
    != "CreateProductionEventSourceMappings"
):
    failures.append(
        "bootstrap template: lambda:CreateEventSourceMapping must stay in CreateProductionEventSourceMappings in the CloudFormation execution role policy"
    )

event_source_mapping_tag_actions = [
    (role_name, policy_name, statement)
    for role_name, policy_name, statement in all_iam_role_policy_statements
    if "lambda:TagResource" in as_list(statement.get("Action"))
    and statement.get("Resource") == event_source_mapping_resource
]
if len(event_source_mapping_tag_actions) != 1:
    failures.append(
        "bootstrap template: mapping lambda:TagResource must occur only in CreateProductionEventSourceMappings"
    )
elif (
    event_source_mapping_tag_actions[0][:2]
    != ("OpnFormCloudFormationExecutionRole", "OpnFormProductionStack")
    or event_source_mapping_tag_actions[0][2].get("Sid")
    != "CreateProductionEventSourceMappings"
):
    failures.append(
        "bootstrap template: mapping lambda:TagResource must stay in CreateProductionEventSourceMappings in the CloudFormation execution role policy"
    )

for role_name, policy_name, statement in all_iam_role_policy_statements:
    if "lambda:TagResource" not in as_list(statement.get("Action")):
        continue
    is_mapping_tag_statement = (
        (role_name, policy_name, statement.get("Sid"))
        == (
            "OpnFormCloudFormationExecutionRole",
            "OpnFormProductionStack",
            "CreateProductionEventSourceMappings",
        )
        and statement.get("Resource") == event_source_mapping_resource
    )
    is_function_tag_statement = (
        (role_name, policy_name, statement.get("Sid"))
        == (
            "OpnFormCloudFormationExecutionRole",
            "OpnFormProductionStack",
            "ManageProductionFunctions",
        )
        and statement.get("Resource")
        == "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-prod-*"
    )
    is_ui_shadow_function_tag_statement = (
        (role_name, policy_name, statement.get("Sid"))
        == (
            "OpnFormCloudFormationExecutionRole",
            "OpnFormProductionStack",
            "ManageUiShadowFunctions",
        )
        and statement.get("Resource")
        == "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-ui-shadow-*"
    )
    if not is_mapping_tag_statement and not is_function_tag_statement and not is_ui_shadow_function_tag_statement:
        failures.append(
            "bootstrap template: lambda:TagResource may only tag approved production functions, UI shadow functions, or event-source mappings"
        )

expected_http_api_actions = {
    "apigateway:DELETE",
    "apigateway:GET",
    "apigateway:PATCH",
    "apigateway:POST",
    "apigateway:PUT",
    "apigateway:TagResource",
}
manage_http_api = [
    statement for statement in execution_statements if statement.get("Sid") == "ManageHttpApi"
]
if len(manage_http_api) != 1:
    failures.append("bootstrap template: execution role must have exactly one ManageHttpApi statement")
else:
    statement = manage_http_api[0]
    actions = as_list(statement.get("Action"))
    if set(actions) != expected_http_api_actions or len(actions) != len(expected_http_api_actions):
        failures.append(
            "bootstrap template: ManageHttpApi must enumerate only the approved HTTP API actions including apigateway:TagResource"
        )
    if statement.get("Resource") != "*":
        failures.append("bootstrap template: ManageHttpApi resource scope must remain '*' for HTTP API control plane")
for statement in execution_statements:
    api_actions = [
        action for action in as_list(statement.get("Action")) if isinstance(action, str) and action.startswith("apigateway:")
    ]
    if api_actions and statement.get("Sid") != "ManageHttpApi":
        failures.append("bootstrap template: execution role API Gateway actions must stay in ManageHttpApi")
for statement in deploy_statements:
    api_actions = [
        action for action in as_list(statement.get("Action")) if isinstance(action, str) and action.startswith("apigateway:")
    ]
    if api_actions:
        failures.append("bootstrap template: GitHub deploy role must not grant API Gateway actions")

bref_external_account_id = "534081306603"
bref_layer_version_arns = {
    "arn:aws:lambda:us-east-1:534081306603:layer:php-83-fpm:70",
    "arn:aws:lambda:us-east-1:534081306603:layer:php-83:70",
    "arn:aws:lambda:us-east-1:534081306603:layer:console:122",
}
approved_bref_layer_arn_pattern = re.compile(
    r"(?<![A-Za-z0-9:._/-])(?:"
    + "|".join(re.escape(arn) for arn in bref_layer_version_arns)
    + r")(?![A-Za-z0-9:._/-])"
)
approved_bref_layer_arn_matches = list(approved_bref_layer_arn_pattern.finditer(template))
if (
    len(approved_bref_layer_arn_matches) != len(bref_layer_version_arns)
    or {match.group() for match in approved_bref_layer_arn_matches} != bref_layer_version_arns
):
    failures.append(
        "bootstrap template: each approved Bref layer version ARN must occur exactly once"
    )
for account_id_match in re.finditer(re.escape(bref_external_account_id), template):
    if not any(
        arn_match.start() <= account_id_match.start()
        and account_id_match.end() <= arn_match.end()
        for arn_match in approved_bref_layer_arn_matches
    ):
        failures.append(
            "bootstrap template: Bref external account ID may appear only in the approved layer version ARNs"
        )
        break
bref_layer_metadata_statements = [
    statement
    for statement in execution_statements
    if statement.get("Sid") == "ReadBrefLayerVersionMetadata"
]
if len(bref_layer_metadata_statements) != 1:
    failures.append(
        "bootstrap template: execution role must have exactly one ReadBrefLayerVersionMetadata statement"
    )
else:
    statement = bref_layer_metadata_statements[0]
    resources = statement.get("Resource")
    if as_list(statement.get("Action")) != ["lambda:GetLayerVersion"]:
        failures.append(
            "bootstrap template: ReadBrefLayerVersionMetadata must allow only lambda:GetLayerVersion"
        )
    if (
        not isinstance(resources, list)
        or set(resources) != bref_layer_version_arns
        or len(resources) != len(bref_layer_version_arns)
    ):
        failures.append(
            "bootstrap template: ReadBrefLayerVersionMetadata must list exactly the approved Bref layer version ARNs"
        )
for role_label, statements in (
    ("execution role", execution_statements),
    ("GitHub deploy role", deploy_statements),
):
    for statement in statements:
        actions = as_list(statement.get("Action"))
        resources = as_list(statement.get("Resource"))
        if "lambda:GetLayerVersion" in actions and (
            role_label != "execution role"
            or statement.get("Sid") != "ReadBrefLayerVersionMetadata"
        ):
            failures.append(
                f"bootstrap template: {role_label} must not grant lambda:GetLayerVersion outside ReadBrefLayerVersionMetadata"
            )
        for resource in resources:
            if isinstance(resource, str) and ":layer:" in resource and (
                role_label != "execution role"
                or statement.get("Sid") != "ReadBrefLayerVersionMetadata"
                or resource not in bref_layer_version_arns
            ):
                failures.append(
                    "bootstrap template: Bref layer resources must stay in ReadBrefLayerVersionMetadata and match the approved versions"
                )

function_metadata_arn = "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:opnform-prod-*"
function_metadata_statements = [
    statement for statement in deploy_statements if statement.get("Sid") == "ReadProductionFunctionMetadata"
]
if len(function_metadata_statements) != 1:
    failures.append("bootstrap template: GitHub deploy role must have exactly one ReadProductionFunctionMetadata statement")
else:
    statement = function_metadata_statements[0]
    if as_list(statement.get("Action")) != ["lambda:GetFunction"]:
        failures.append("bootstrap template: ReadProductionFunctionMetadata must allow only lambda:GetFunction")
    if statement.get("Resource") != function_metadata_arn:
        failures.append("bootstrap template: ReadProductionFunctionMetadata resource scope changed")
allowed_deploy_lambda_statements = {
    "ReadProductionFunctionMetadata": (["lambda:GetFunction"], function_metadata_arn),
    "InvokeOnlyProductionArtisan": (["lambda:InvokeFunction"], expected_artisan_arn),
}
for statement in deploy_statements:
    lambda_actions = [
        action for action in as_list(statement.get("Action")) if isinstance(action, str) and action.startswith("lambda:")
    ]
    if not lambda_actions:
        continue
    sid = statement.get("Sid")
    expected = allowed_deploy_lambda_statements.get(sid) if isinstance(sid, str) else None
    if expected is None:
        failures.append("bootstrap template: GitHub deploy role has an unapproved Lambda statement")
        continue
    expected_actions, expected_resource = expected
    if lambda_actions != expected_actions:
        failures.append(f"bootstrap template: {sid} Lambda actions changed")
    if statement.get("Resource") != expected_resource:
        failures.append(f"bootstrap template: {sid} Lambda resource scope changed")
read_production_stack = re.search(
    r"(?ms)^[ \t]+- Sid: ReadProductionStack\n(.*?)(?=^[ \t]+- Sid:|\Z)", template
)
if read_production_stack is None:
    failures.append("bootstrap template: ReadProductionStack statement is missing")
else:
    statement = read_production_stack.group(1)
    if not re.search(r"(?m)^[ \t]+- cloudformation:DescribeStackResource\s*$", statement):
        failures.append(
            "bootstrap template: ReadProductionStack must allow cloudformation:DescribeStackResource"
        )
    if "Resource: !Sub 'arn:aws:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/opnform-prod/*'" not in statement:
        failures.append("bootstrap template: ReadProductionStack resource scope changed")
subjects = re.findall(r"token\.actions\.githubusercontent\.com:sub:\s*([^\s]+)", template)
if subjects != ["repo:TotalLag@1744428/OpnForm@1317796294:environment:opnform-prod"]:
    failures.append("bootstrap template: OIDC subject must be exactly the opnform-prod environment subject")
for policy in ("AdministratorAccess", "PowerUserAccess"):
    forbid(template, policy, "bootstrap template")
forbid(template, r"(?:Action:[ \t]*['\"]?(?:\*|[A-Za-z0-9_-]+:\*)|^[ \t]*-[ \t]+[A-Za-z0-9_-]+:\*)", "bootstrap template")
for source_name, content in (
    ("serverless configuration", serverless),
    ("deployment workflow", workflow),
    ("bootstrap template", template),
):
    public_bref_spans = (
        [(match.start(), match.end()) for match in approved_bref_layer_arn_matches]
        if source_name == "bootstrap template"
        else []
    )
    for account_id_match in re.finditer(r"\b\d{12}\b", content):
        if not any(start <= account_id_match.start() and account_id_match.end() <= end for start, end in public_bref_spans):
            failures.append(f"{source_name}: owner-style literal account IDs are forbidden")
            break
    forbid(content, r"\bopnform-(?:prod-serverless|ui-shadow-artifacts)-\d{12}-us-east-1\b", source_name)
    forbid(content, r"\bus-(?!east-1\b)[a-z]+-\d+\b", source_name)

ui_shadow_check = subprocess.run(
    [sys.executable, "client/infra/aws/check-ui-shadow.py", "--self-test"],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if ui_shadow_check.returncode:
    failures.append(
        "UI shadow validator failed: " + (ui_shadow_check.stdout + ui_shadow_check.stderr).strip()
    )

if failures:
    print("Direct AWS deployment boundary violations:")
    print("\n".join(f"- {failure}" for failure in failures))
    raise SystemExit(1)

print("Direct AWS deployment boundaries passed")
