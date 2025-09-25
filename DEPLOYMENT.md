# Automated Serverless Deployment Guide (Bref + NuxtHub)

This project is configured for a fully serverless architecture using [Bref](https://bref.sh/) on [AWS Lambda](https://aws.amazon.com/lambda/) for the backend and [NuxtHub](https://hub.nuxt.com/) for the frontend.

The deployment process is automated with GitHub Actions, providing separate workflows for **Production** and **Preview** environments.

---

## Architecture Overview

-   **Backend:** The Laravel API in the `api/` directory is deployed as a serverless application using Bref. This includes the web server, queue workers, and scheduled tasks, all running on AWS Lambda.
-   **Frontend:** The Nuxt.js UI in the `client/` directory is deployed to NuxtHub's global edge network.
-   **CI/CD:** GitHub Actions orchestrate the entire deployment process, triggered by pushes and pull requests to your repository.

---

## Deployment Workflows

### Production Environment

The production environment is your live, public-facing application.

-   **Trigger:** Automatically deploys on every push or merge to the `main` branch.
-   **Action:** The `.github/workflows/production.yml` workflow uses the Serverless Framework to deploy the backend to a permanent `prod` stage on AWS.
-   **Frontend:** The production frontend is deployed via NuxtHub's native Git integration, which monitors the `main` branch.

### Preview Environments

A temporary, isolated preview environment is created for every pull request.

-   **Trigger:** Automatically runs when a pull request is opened, updated, or closed.
-   **Backend Action:** The `.github/workflows/preview.yml` workflow deploys the backend to a temporary, dynamic stage on AWS (e.g., `pr-123`).
-   **Frontend Action:** The workflow then deploys a corresponding frontend preview to NuxtHub, ensuring it's configured to communicate with the temporary backend.
-   **PR Comment:** A comment is automatically posted to the pull request with a link to the live frontend preview.
-   **Cleanup:** When the pull request is closed, the workflow automatically destroys all the temporary AWS resources to save costs.

---

## Initial Setup Guide

To enable these automated workflows, you must perform the following one-time setup.

### 1. AWS Account and IAM Roles

1.  **Create an AWS Account:** If you don't have one, [sign up for AWS](https://aws.amazon.com/).
2.  **Configure IAM Roles for GitHub Actions:** For maximum security, it's best to use AWS IAM roles to grant GitHub Actions permission to deploy resources. Follow the official [AWS guide to configure OpenID Connect](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html). You will need to create two roles:
    *   A role for production deployments (e.g., `github-actions-prod-deployer`).
    *   A role for preview deployments (e.g., `github-actions-preview-deployer`), which should have more limited permissions if desired.

### 2. NuxtHub Projects

1.  **Production Project:** Create a project on NuxtHub for your production frontend. Link it to the `main` branch of your GitHub repository. In the project settings, set the **Root Directory** to `client`.
2.  **Preview Project:** Create a second project on NuxtHub to be used for all previews (e.g., `opnform-previews`). You do *not* need to link this to a specific branch.

### 3. GitHub Secrets

In your GitHub repository, go to `Settings > Secrets and variables > Actions` and add the following secrets.

-   `AWS_IAM_ROLE_PROD`: The full ARN of the IAM role you created for production deployments.
-   `AWS_IAM_ROLE_PREVIEW`: The full ARN of the IAM role for preview deployments.
-   `NUXT_HUB_USER_TOKEN`: Your personal user token from the NuxtHub Admin dashboard (`User settings > Tokens`).
-   `NUXT_HUB_PROJECT_KEY_PREVIEW`: The project key for your **preview** NuxtHub project.

*(Note: If you choose not to use IAM Roles, you can instead create an IAM User and set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as secrets.)*

### 4. Production Environment Variables

1.  **Backend (AWS):** For your production backend, store sensitive values like your database password and `APP_KEY` in the [AWS Systems Manager (SSM) Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html). The `serverless.yml` can be configured to read these securely.
2.  **Frontend (NuxtHub):** In your production NuxtHub project's settings, you must set the `NUXT_PUBLIC_API_URL` environment variable to the public URL of your production backend API. You will get this URL after the first successful production deployment.