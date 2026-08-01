<?php

use Illuminate\Queue\SqsQueue;
use Illuminate\Support\Facades\Queue;
use Laravel\Vapor\Queue\VaporQueue;

it('resolves an SQS connection with temporary credentials through Illuminate', function () {
    config()->set('queue.connections.session-token-sqs', [
        'driver' => 'sqs',
        'key' => 'temporary-access-key',
        'secret' => 'temporary-secret-key',
        'token' => 'temporary-session-token',
        'prefix' => 'https://sqs.us-east-1.amazonaws.com',
        'queue' => 'form-submissions',
        'region' => 'us-east-1',
    ]);

    $connection = Queue::connection('session-token-sqs');

    expect($connection)
        ->toBeInstanceOf(SqsQueue::class)
        ->not->toBeInstanceOf(VaporQueue::class);
});
