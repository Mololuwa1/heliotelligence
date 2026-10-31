# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.

## Authentication and authorization

API requests use the verified Firebase bearer token attached by `src/api/client.js`. No browser administrator secret or extra administrator header is required or supported. The server admits global administration only from the exact `platform_admin=true` custom claim; site access uses explicit database viewer/admin membership. Existing admin navigation may return 403 for ordinary users until separate UI work hides it. Hiding navigation is never a security boundary.

Configure only the public Firebase/API/Mapbox settings in `.env.staging.example`. Trusted platform-admin claim provisioning is out of band and requires a newly issued/refreshed token; no claim-assignment UI or endpoint is added. See the [server policy and bootstrap procedure](../docs/architecture/platform-authorization.md).
