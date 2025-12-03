<?php

namespace App\Jobs\Form;

use App\Models\Forms\Form;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\Middleware\WithoutOverlapping;
use Illuminate\Queue\SerializesModels;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class RevalidateFrontendJob implements ShouldQueue
{
    use Dispatchable;
    use InteractsWithQueue;
    use Queueable;
    use SerializesModels;

    public function __construct(
        public int $formId,
        public ?array $extraPaths = null
    ) {
    }

    public int $tries = 5;

    public int $timeout = 15;

    public function backoff(): array
    {
        // exponential-ish backoff in seconds
        return [2, 5, 10, 20, 30];
    }

    public function middleware(): array
    {
        // Avoid overlapping refreshes for the same form
        return [new WithoutOverlapping("form-revalidate-{$this->formId}")];
    }

    public function handle(): void
    {
        // Use helper to resolve front URL from config (falls back to app.url)
        $webBase = rtrim(\front_url(''), '/');
        // Read secret from environment (rendered into NGINX and sent via header)
        $token   = \env('REFRESH_TOKEN', '');
        if (!$webBase || !$token) {
            Log::warning('RevalidateFrontendJob: FRONT_URL or REFRESH_TOKEN not set, skipping.', [
                'form_id' => $this->formId,
            ]);
            return;
        }
        $endpoint = $webBase . '/__refresh';

        /** @var Form $form */
        $form = Form::find($this->formId);
        if (!$form) {
            Log::warning('RevalidateFrontendJob: form not found, skipping.', [
                'form_id' => $this->formId,
            ]);
            return;
        }

        $slug = $form->slug ?? (string) $form->id;

        // Base set of pages to pre-warm; only public, cacheable pages
        $paths = array_filter([
            "/forms/{$slug}",
        ]);

        // Allow callers to append more specific pages
        if (is_array($this->extraPaths) && !empty($this->extraPaths)) {
            foreach ($this->extraPaths as $p) {
                if (is_string($p) && str_starts_with($p, '/')) {
                    $paths[] = $p;
                }
            }
        }

        // De-duplicate
        $paths = array_values(array_unique($paths));

        $allOk = true;

        foreach ($paths as $path) {
            try {
                $resp = Http::timeout(20)
                    ->retry(3, 1000)
                    ->withHeaders([
                        'X-Refresh-Token' => $token,
                        'Accept' => 'application/json',
                        'User-Agent' => 'OpnForm-Refresh/1.0',
                    ])
                    // Build full URL to avoid encoding leading slash ("/" -> "%2F")
                    ->get($endpoint . '?p=' . $path);

                if (!$resp->successful()) {
                    Log::warning('RevalidateFrontendJob: refresh call failed', [
                        'form_id' => $this->formId,
                        'path' => $path,
                        'status' => $resp->status(),
                        'body' => $resp->body(),
                        'cache' => $resp->header('X-Cache-Status'),
                        'bypass' => $resp->header('X-Cache-Bypass'),
                    ]);
                    $allOk = false;
                } else {
                    Log::info('RevalidateFrontendJob: refreshed frontend path', [
                        'form_id' => $this->formId,
                        'path' => $path,
                        'cache' => $resp->header('X-Cache-Status'),
                        'bypass' => $resp->header('X-Cache-Bypass'),
                    ]);
                }
            } catch (\Throwable $e) {
                Log::error('RevalidateFrontendJob: exception while calling refresh endpoint', [
                    'form_id' => $this->formId,
                    'path' => $path,
                    'error' => $e->getMessage(),
                ]);
                $allOk = false;
            }
        }

        if (!$allOk) {
            throw new \RuntimeException('One or more refresh requests failed');
        }
    }
}
