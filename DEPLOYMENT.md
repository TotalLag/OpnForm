# Deploying OpnForm with a Hybrid Model (Fly.io + NuxtHub)

This guide provides step-by-step instructions for deploying the OpnForm application using a hybrid model:
- **Backend API:** Deployed on [Fly.io](https://fly.io/) by building from the source Dockerfile.
- **Frontend UI:** Deployed on [NuxtHub](https://hub.nuxt.com/) for optimized Nuxt application hosting.

## Prerequisites

- A [Fly.io](https://fly.io/) account.
- A [NuxtHub](https://hub.nuxt.com/) account, connected to your GitHub account.
- The `flyctl` command-line tool installed and authenticated.
- A clone of the OpnForm repository pushed to your own GitHub repository.
- An S3-compatible object storage bucket and credentials.

## 1. Backend Deployment (Fly.io)

### Step 1: Provision the Database and Cache

First, provision a PostgreSQL database and a Redis cache on Fly.io.

**PostgreSQL:**
```bash
fly postgres create --name opnform-db --region <your-region>
```

**Redis:**
```bash
fly redis create --name opnform-redis --region <your-region>
```

### Step 2: Configure and Deploy the API

The `api/fly.toml` file is pre-configured to deploy the backend by building from the `docker/Dockerfile.api` file in this repository.

**Important:** Before deploying, you must update the `APP_URL` in `api/fly.toml` to your final NuxtHub frontend URL.

You will also need to set the following secrets to connect to your database, Redis, and S3 bucket.

**Required Secrets:**
- `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`: Your PostgreSQL credentials.
- `DB_HOST`: The internal hostname of your Fly.io PostgreSQL database (e.g., `opnform-db.internal`).
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `AWS_BUCKET`: Your S3 bucket credentials and information.
- `AWS_ENDPOINT`: The endpoint URL for your S3-compatible service (if not using AWS S3).

Set these secrets using the `flyctl` command:
```bash
fly secrets set -a opnform-api \
  DB_DATABASE=<your-db-name> \
  DB_USERNAME=<your-db-user> \
  DB_PASSWORD=<your-db-password> \
  DB_HOST=opnform-db.internal \
  AWS_ACCESS_KEY_ID=<your-s3-key-id> \
  AWS_SECRET_ACCESS_KEY=<your-s3-secret> \
  AWS_DEFAULT_REGION=<your-s3-region> \
  AWS_BUCKET=<your-s3-bucket-name> \
  AWS_ENDPOINT=<your-s3-endpoint> # (Optional)
```

**Deploy the API:**
```bash
fly deploy -a opnform-api --config api/fly.toml
```
After deployment, note the public URL of your API (e.g., `https://opnform-api.fly.dev`).

## 2. Frontend Deployment (NuxtHub)

### Step 1: Connect Your Repository

In your NuxtHub dashboard, create a new project and connect it to your GitHub repository containing the OpnForm code.

### Step 2: Configure Environment Variables

NuxtHub will automatically detect the Nuxt application in the `client/` directory. The most important step is to tell the frontend where to find the backend API.

In your NuxtHub project settings, add the following environment variable:
- `NUXT_PUBLIC_API_URL`: The public URL of your `opnform-api` Fly.io application.

### Step 3: Deploy

NuxtHub will automatically build and deploy your application from the `main` branch. Once the deployment is complete, you can access your OpnForm application at the URL provided by NuxtHub.
