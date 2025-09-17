# Automated Deployment Guide (Fly.io + NuxtHub)

This project is configured with automated CI/CD workflows using GitHub Actions to deploy the backend API to [Fly.io](https://fly.io/) and the frontend UI to [NuxtHub](https://hub.nuxt.com/).

There are two main deployment environments: **Production** and **Preview**.

---

## Production Environment

The production environment is your live, public-facing application.

### Workflow

- **Trigger:** The production deployment is automatically triggered on every push or merge to the `main` branch.
- **Backend (Fly.io):** The `.github/workflows/production.yml` workflow deploys the API from the `api/` directory to your production Fly.io application.
- **Frontend (NuxtHub):** The production frontend deployment is handled by NuxtHub's native Git integration. When you link your `main` branch to your NuxtHub project, it will automatically deploy any new commits.

---

## Preview Environments

Preview environments are temporary, isolated instances of the application created for every pull request. This allows you to test changes in a live environment before merging them into `main`.

### Workflow

- **Trigger:** The preview workflow is automatically triggered whenever a pull request is opened, updated, or closed.
- **Backend (Fly.io):** A temporary backend app is created on Fly.io, named `opnform-api-pr-<PR_NUMBER>`.
- **Frontend (NuxtHub):** A corresponding frontend preview is deployed to NuxtHub. The workflow ensures that this frontend is configured to communicate with the temporary backend API.
- **PR Comment:** Once the preview environment is ready, a comment is automatically posted to the pull request with a link to the live frontend preview.
- **Automatic Cleanup:** When the pull request is closed (merged or not), the workflow automatically destroys the temporary backend app on Fly.io to save costs.

---

## Initial Setup

To enable these automated workflows, you need to perform the following one-time setup steps.

### 1. Create Production Apps

- **Fly.io:** Create your production backend app. You can name it whatever you like (e.g., `opnform-api-prod`). Note its final URL.
- **NuxtHub:** Create your production frontend project and link it to the `main` branch of your GitHub repository.
  - In the NuxtHub project settings, set the **Root Directory** to `client`.
  - In the NuxtHub project's environment variable settings, add `NUXT_PUBLIC_API_URL` and set its value to the public URL of your production Fly.io app.

### 2. Create a Preview Project on NuxtHub

- **NuxtHub:** Create a second project on NuxtHub specifically for previews (e.g., `opnform-previews`). You do *not* need to link this to a specific branch, as our GitHub Action will deploy to it manually.

### 3. Add GitHub Secrets

In your GitHub repository, go to `Settings > Secrets and variables > Actions` and add the following repository secrets. The workflows use these to authenticate with Fly.io and NuxtHub.

- `FLY_API_TOKEN`: Your API token for Fly.io. You can generate this by running `fly tokens create org <YOUR_ORG_NAME>`.
- `NUXT_HUB_USER_TOKEN`: Your personal user token from the NuxtHub Admin dashboard (`User settings > Tokens`).
- `NUXT_HUB_PROJECT_KEY_PREVIEW`: The project key for your **preview** NuxtHub project.
- **Backend Secrets:** You also need to set any required backend secrets (like database credentials) directly in your Fly.io production app's settings. For preview apps, you can add them to the `preview.yml` workflow file if needed.
