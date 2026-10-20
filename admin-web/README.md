# FRS Admin Web

A Next.js App Router application for the FRS admin console. It is a separate workspace package from the Flutter app and Python backend.

## Requirements

- Node.js 20.9 or newer (Node 22 is recommended).
- pnpm 10 or newer.
- The FRS FastAPI backend running locally or at a trusted HTTPS URL.

## Run locally

From the repository root, run pnpm install, copy admin-web/.env.example to admin-web/.env.local, then run pnpm dev.

Open http://localhost:3000. Set the API base URL and enter the administrator bearer key in the sidebar connection panel. The key is held only in browser memory and is not written to local storage or exposed as a public build-time variable. It is lost when the tab is reloaded.

The backend must allow the website origin in FRS_ALLOWED_ORIGINS (for local development, include http://localhost:3000) and be reachable from the browser. The console uses existing endpoints for health, people, attendance, and the model registry.

## Current scope

Implemented in Sprint 1: live backend health; admin-key connection check; real people/attendance/model-registry queries; person deactivate/reactivate actions; error and disconnected states.

Not yet implemented: institutional user authentication/role management, college department-year-section schema and CRUD, Supabase migrations/RLS, Cloudinary upload lifecycle, capture-batch jobs, or enrollment image management. Do not expose this development console publicly until institutional authentication and authorization are implemented and reviewed.

The backend API currently models a generic person/department and is not yet a college class/section data model. The website deliberately does not invent or display fake class/student data.
