<?php

namespace App\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/**
 * Laravel API controller fixture.
 *
 * Expected score: 50-70
 *   + response()->json(      → strong  +30
 *   + ->toResponse(          → strong  +30
 *   + json_encode(           → weak    +10
 *   + Illuminate\Http\JsonResponse (import) → weak +10
 *   - return view(           → negative -15
 *   Total: 65  (within 50-70)
 */
class UserController extends Controller
{
    /**
     * GET /api/users — returns a JSON list of users.
     * Strong signal: response()->json(
     */
    public function index(): JsonResponse
    {
        $users = [
            ['id' => 1, 'name' => 'Alice', 'email' => 'alice@example.com'],
            ['id' => 2, 'name' => 'Bob',   'email' => 'bob@example.com'],
        ];

        return response()->json([
            'success' => true,
            'data'    => $users,
            'message' => 'Users retrieved successfully',
        ]);
    }

    /**
     * POST /api/users — creates a user and returns a resource.
     * Strong signal: ->toResponse(
     */
    public function store(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'name'  => 'required|string|max:255',
            'email' => 'required|email',
        ]);

        // Simulate persisting
        $user = array_merge(['id' => 99], $validated);

        // Returns via resource toResponse — another strong signal
        $resourceData = (object) $user;
        return $resourceData->toResponse($request);
    }

    /**
     * GET /api/users/{id}/export — raw json_encode usage (weak signal).
     */
    public function export(Request $request, int $id)
    {
        $data = ['id' => $id, 'export' => true, 'format' => 'json'];
        $json = json_encode($data, JSON_PRETTY_PRINT);
        return response($json, 200)->header('Content-Type', 'application/json');
    }

    /**
     * GET /users/dashboard — renders a Blade view (negative signal).
     */
    public function dashboard()
    {
        $data = ['title' => 'Dashboard', 'count' => 42];
        return view('users.dashboard', $data);
    }

    /**
     * GET /users/{id}/report — returns a file download (neutral).
     */
    public function download(int $id)
    {
        $filePath = storage_path("reports/user_{$id}.csv");
        return response()->download($filePath);
    }
}
