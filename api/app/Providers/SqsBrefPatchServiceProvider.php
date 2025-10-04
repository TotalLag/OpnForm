<?php

namespace App\Providers;

use Aws\Sqs\SqsClient;
use Illuminate\Queue\QueueManager;
use Illuminate\Queue\Connectors\SqsConnector;
use Illuminate\Support\ServiceProvider;

class SqsBrefPatchServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->booted(function () {
            $manager = $this->app->make(QueueManager::class);

            $manager->addConnector('sqs', function () {
                return new SqsConnector(function (array $config) {
                    unset($config['key'], $config['secret'], $config['token']);

                    return new SqsClient([
                        'version' => 'latest',
                        'region'  => $config['region'] ?? env('AWS_DEFAULT_REGION', 'us-east-1'),
                        'credentials' => array_filter([
                            'key'    => env('AWS_ACCESS_KEY_ID'),
                            'secret' => env('AWS_SECRET_ACCESS_KEY'),
                            'token'  => env('AWS_SESSION_TOKEN'),
                        ]) ?: null,
                    ]);
                });
            });
        });
    }
}
