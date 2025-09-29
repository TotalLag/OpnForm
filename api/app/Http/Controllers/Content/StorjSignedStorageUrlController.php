<?php

namespace App\Http\Controllers\Content;

use Aws\S3\S3Client;
use Illuminate\Http\Request;
use Illuminate\Support\Str;
use Laravel\Vapor\Http\Controllers\SignedStorageUrlController as BaseController;

class StorjSignedStorageUrlController extends BaseController
{
    /**
     * Create a new signed URL (no Gate authorization; mirrors existing app controller behavior).
     */
    public function store(Request $request)
    {
        $this->ensureEnvironmentVariablesAreAvailable($request);
        $bucket = $request->input('bucket') ?: $_ENV['AWS_BUCKET'];

        $client = $this->storageClient();

        $uuid = (string) Str::uuid();

        $expiresAfter = config('vapor.signed_storage_url_expires_after', 5);

        $signedRequest = $client->createPresignedRequest(
            $this->createCommand($request, $client, $bucket, $key = ('tmp/' . $uuid)),
            sprintf('+%s minutes', $expiresAfter)
        );

        $uri = $signedRequest->getUri();

        return response()->json([
            'uuid' => $uuid,
            'bucket' => $bucket,
            'key' => $key,
            'url' => $uri->getScheme() . '://' . $uri->getAuthority() . $uri->getPath() . '?' . $uri->getQuery(),
            'headers' => $this->headers($request, $signedRequest),
        ], 201);
    }

    /**
     * Determine if we are targeting Storj (or another non-AWS S3-compatible) endpoint.
     */
    protected function isStorj(): bool
    {
        $endpoint = env('AWS_ENDPOINT', env('AWS_URL', ''));
        return is_string($endpoint) && stripos($endpoint, 'storjshare.io') !== false;
    }

    /**
     * Override the PUT command used for presigned URLs.
     * - Storj does not support ACLs, so omit 'ACL' when targeting Storj.
     */
    protected function createCommand(Request $request, S3Client $client, $bucket, $key)
    {
        $params = [
            'Bucket'       => $bucket,
            'Key'          => $key,
            'ContentType'  => $request->input('content_type') ?: 'application/octet-stream',
            'CacheControl' => $request->input('cache_control') ?: null,
            'Expires'      => $request->input('expires') ?: null,
        ];

        if (! $this->isStorj()) {
            // Only include ACL when using AWS S3; Storj gateways typically do not support ACLs
            $params['ACL'] = $request->input('visibility') ?: $this->defaultVisibility();
        }

        return $client->getCommand('putObject', array_filter($params));
    }

    /**
     * Override the S3 client used for presigned URLs to force a Storj/S3-compatible endpoint.
     */
    protected function storageClient()
    {
        $endpoint = env('AWS_ENDPOINT', env('AWS_URL', 'https://gateway.storjshare.io'));

        $config = [
            'version'                 => 'latest',
            'region'                  => env('AWS_DEFAULT_REGION', 'us-east-1'),
            'signature_version'       => 'v4',
            'use_path_style_endpoint' => true,
            'endpoint'                => $endpoint,
            // Some gateways require an explicit signing region; keep consistent with provider/defaults.
            'signing_region'          => env('AWS_SIGNING_REGION', 'us-east-1'),
        ];

        // Prefer STORJ_* but fall back to AWS_*; exclude STS token when targeting Storj gateways
        $credentials = [
            'key'    => env('STORJ_KEY', env('AWS_ACCESS_KEY_ID')),
            'secret' => env('STORJ_SECRET', env('AWS_SECRET_ACCESS_KEY')),
        ];

        if (! $this->isStorj()) {
            // Only include session token when using AWS S3
            $token = env('AWS_SESSION_TOKEN');
            if (!empty($token)) {
                $credentials['token'] = $token;
            }
        }

        $credentials = array_filter($credentials);

        if (!empty($credentials)) {
            $config['credentials'] = $credentials;
        }

        return new S3Client($config);
    }
}
