<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class RewriteApiHostToFrontend
{
    public function handle(Request $request, Closure $next)
    {
        $response = $next($request);

        // Frontend base to expose publicly
        $frontBase = rtrim((string) config('app.front_url', ''), '/');
        // Private API base to hide
        $apiBase = rtrim((string) config('app.url', ''), '/');

        // If either base is missing, skip
        if (empty($frontBase) || empty($apiBase) || $frontBase === $apiBase) {
            return $response;
        }

        // Only process JSON responses
        if ($response instanceof JsonResponse) {
            $data = $response->getData(true);

            $transform = function ($value) use (&$transform, $apiBase, $frontBase) {
                if (is_array($value)) {
                    foreach ($value as $k => $v) {
                        $value[$k] = $transform($v);
                    }
                    return $value;
                }

                if (is_string($value)) {
                    // Never touch signed URLs; changing host may invalidate signature
                    if (stripos($value, 'signature=') !== false) {
                        return $value;
                    }

                    // Replace absolute API origin with frontend origin
                    if (str_starts_with($value, $apiBase . '/')) {
                        return $frontBase . substr($value, strlen($apiBase));
                    }
                }

                return $value;
            };

            $data = $transform($data);
            $response->setData($data);
        }

        return $response;
    }
}
