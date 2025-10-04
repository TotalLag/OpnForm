<?php

namespace App\Listeners\Forms;

use App\Events\Forms\FormSaved;
use App\Jobs\Form\RevalidateFrontendJob;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Support\Facades\Bus;

class RevalidateFrontendOnFormSaved implements ShouldQueue
{
    /**
     * Handle the event.
     *
     * When a form is saved, enqueue a job to pre-warm the Nuxt SSR cache
     * for the key routes where this form is rendered.
     */
    public function handle(FormSaved $event): void
    {
        $form = $event->form;

        // Prefer slug when available (fallback to ID)
        $slug = $form->slug ?? (string) $form->id;

        // Primary pages that render this form (extend as needed)
        $paths = array_filter([
            "/forms/{$slug}",
        ]);

        // Dispatch queued job that calls the NGINX /__refresh endpoint (one request per path)
        Bus::dispatch(new RevalidateFrontendJob($form->id, $paths));
    }
}
