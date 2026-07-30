<?php

use App\Http\Controllers\HealthCheckController;
use Illuminate\Contracts\Redis\Factory as RedisFactory;

uses(\Tests\TestCase::class);

it('omits Redis when no configured backend uses it', function () {
    config([
        'cache.default' => 'database',
        'session.driver' => 'database',
        'queue.default' => 'sqs',
    ]);

    $response = app(HealthCheckController::class)->apiCheck();

    expect($response->getStatusCode())->toBe(200)
        ->and($response->getData(true))->toBe([
            'status' => 'ok',
            'dependencies' => ['database' => true],
        ]);
});

it('checks Redis when a configured backend uses it', function (string $backend) {
    config([
        'cache.default' => 'database',
        'session.driver' => 'database',
        'queue.default' => 'sqs',
        $backend => 'redis',
    ]);

    $connection = Mockery::mock();
    $connection->shouldReceive('ping')->once()->andReturn(true);

    $factory = Mockery::mock(RedisFactory::class);
    $factory->shouldReceive('connection')->once()->andReturn($connection);
    app()->instance(RedisFactory::class, $factory);

    $response = app(HealthCheckController::class)->apiCheck();

    expect($response->getStatusCode())->toBe(200)
        ->and($response->getData(true))->toBe([
            'status' => 'ok',
            'dependencies' => [
                'database' => true,
                'redis' => true,
            ],
        ]);
})->with([
    'cache' => 'cache.default',
    'session' => 'session.driver',
    'queue' => 'queue.default',
]);

it('fails when a configured Redis dependency is unavailable', function () {
    config([
        'cache.default' => 'redis',
        'session.driver' => 'database',
        'queue.default' => 'sqs',
    ]);

    $factory = Mockery::mock(RedisFactory::class);
    $factory->shouldReceive('connection')->once()->andThrow(new RuntimeException('unavailable'));
    app()->instance(RedisFactory::class, $factory);

    $response = app(HealthCheckController::class)->apiCheck();

    expect($response->getStatusCode())->toBe(503)
        ->and($response->getData(true))->toBe([
            'status' => 'error',
            'dependencies' => [
                'database' => true,
                'redis' => false,
            ],
        ]);
});
