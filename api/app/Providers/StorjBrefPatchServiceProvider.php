<?php

namespace App\Providers;

use Aws\S3\S3Client;
use Illuminate\Filesystem\FilesystemAdapter;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\ServiceProvider;
use League\Flysystem\AwsS3V3\AwsS3V3Adapter;
use League\Flysystem\Filesystem;

class StorjBrefPatchServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->booted(function () {

            /**
             * 📦 1. Re-register the `s3` driver AFTER Vapor/Bref do theirs.
             *     Ensures we always override the default S3 configuration.
             */
            Storage::extend('s3', function ($app, $config) {
                // Remove unsupported keys
                unset($config['token']);

                // ✅ Create an S3 client pointed to Storj or another S3-compatible endpoint
                $client = new S3Client([
                    'version'                 => 'latest',
                    'region'                  => $config['region'] ?? env('AWS_DEFAULT_REGION', 'us-east-1'),
                    'endpoint'                => env('AWS_ENDPOINT', 'https://gateway.storjshare.io'),
                    'use_path_style_endpoint' => true,
                    'signature_version'       => 'v4',
                    'signing_region'          => 'us-east-1',

                    // ✅ Prefer STORJ_* credentials but fallback to AWS_* if not present
                    'credentials'             => [
                        'key'    => env('STORJ_KEY', env('AWS_ACCESS_KEY_ID')),
                        'secret' => env('STORJ_SECRET', env('AWS_SECRET_ACCESS_KEY')),
                    ],
                ]);

                // ✅ Create Flysystem adapter
                $adapter = new AwsS3V3Adapter(
                    $client,
                    $config['bucket'] ?? env('AWS_BUCKET'),
                    $config['prefix'] ?? ''
                );

                // ✅ Return a proper FilesystemAdapter (what Laravel expects) and wire temporaryUrl presigning
                $filesystemAdapter = new FilesystemAdapter(
                    new Filesystem($adapter),
                    $adapter,
                    $config
                );

                // 🔐 Enable temporaryUrl() for S3/Storj by presigning GetObject with the same S3 client
                $filesystemAdapter->buildTemporaryUrlsUsing(function ($path, $expiration, $options) use ($client, $config) {
                    $bucket = $config['bucket'] ?? env('AWS_BUCKET');
                    $prefix = $config['prefix'] ?? '';

                    // Combine prefix with the relative path to form the actual object key
                    $key = ltrim(($prefix ? rtrim($prefix, '/').'/' : '').ltrim($path, '/'), '/');

                    $params = array_filter(array_merge([
                        'Bucket' => $bucket,
                        'Key'    => $key,
                    ], $options ?? []));

                    $command = $client->getCommand('GetObject', $params);
                    $request = $client->createPresignedRequest($command, $expiration);
                    $url = (string) $request->getUri();

                    // Optional host rewrites (useful when internal presign host differs from public)
                    $rewrites = $config['temporary_url_rewrites'] ?? [];
                    foreach ($rewrites as $from => $to) {
                        $url = str_replace($from, $to, $url);
                    }

                    return $url;
                });

                return $filesystemAdapter;
            });


        });
    }
}
