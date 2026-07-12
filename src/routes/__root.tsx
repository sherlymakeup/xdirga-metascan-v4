import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { AppSidebar, MobileBottomNav, MobileSidebarDrawer } from "@/components/cockpit/sidebar";
import { TopStatusBar } from "@/components/cockpit/top-status-bar";
import { ConnectionBanner } from "@/components/runtime/ConnectionBanner";
import { SchemaMismatchBanner } from "@/components/runtime/SchemaMismatchBanner";
import { ExecutionUnknownBanner } from "@/components/runtime/ExecutionUnknownBanner";
import { GlobalOperationalStateBanner } from "@/components/runtime/GlobalOperationalStateBanner";
import { DemoWatermark } from "@/components/runtime/DemoWatermark";
import { ProdFixtureGuard } from "@/components/runtime/ProdFixtureGuard";
import { PRODUCT_BRAND, ROOT_TITLE } from "@/lib/constants/brand";
import { Toaster } from "@/components/ui/sonner";
import { bootstrapEventPipeline } from "@/lib/runtime/events/bootstrap";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 text-center">
      <div className="max-w-md">
        <div className="num text-6xl font-semibold text-muted-foreground">404</div>
        <h1 className="mt-3 text-lg font-semibold">Route not found</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          The runtime cockpit has no page at this address.
        </p>
        <a
          href="/"
          className="mt-4 inline-flex rounded-sm border border-panel-border bg-panel-elevated px-3 py-1.5 text-xs hover:bg-muted"
        >
          Return to Cockpit
        </a>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel max-w-lg p-6 text-center">
        <div className="mx-auto grid h-10 w-10 place-items-center rounded-full bg-status-crit/15 text-status-crit">
          !
        </div>
        <h1 className="mt-3 text-sm font-semibold uppercase tracking-wider text-status-crit">
          Cockpit render failure
        </h1>
        <p className="mt-1 text-xs text-muted-foreground">
          A UI component raised an uncaught exception. The trading runtime is unaffected — the UI is a monitor only.
        </p>
        <pre className="num mt-3 max-h-40 overflow-auto rounded-sm border border-panel-border bg-background p-2 text-left text-[11px] text-muted-foreground">
          {error.message}
        </pre>
        <div className="mt-4 flex justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="rounded-sm bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
          >
            Retry
          </button>
          <a
            href="/"
            className="rounded-sm border border-panel-border bg-panel-elevated px-3 py-1.5 text-xs"
          >
            Back to Cockpit
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
      { name: "theme-color", content: "#0d1117" },
      { title: ROOT_TITLE },
      {
        name: "description",
        content: `${PRODUCT_BRAND.name} — ${PRODUCT_BRAND.descriptor}. ${PRODUCT_BRAND.tagline} Runtime engine: ${PRODUCT_BRAND.runtimeName}.`,
      },
      { property: "og:title", content: ROOT_TITLE },
      {
        property: "og:description",
        content: `${PRODUCT_BRAND.tagline} Local-first control plane powered by ${PRODUCT_BRAND.runtimeName}.`,
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [
      { rel: "stylesheet", href: appCss },
      { rel: "icon", href: "/favicon.ico", type: "image/x-icon" },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap",
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <HeadContent />
      </head>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    bootstrapEventPipeline();
  }, []);



  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex min-h-screen w-full">
        <AppSidebar collapsed={sidebarCollapsed} />
        <MobileSidebarDrawer open={mobileOpen} onClose={() => setMobileOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopStatusBar
            onToggleSidebar={() => {
              if (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches) {
                setSidebarCollapsed((v) => !v);
              } else {
                setMobileOpen((v) => !v);
              }
            }}
          />
          <ProdFixtureGuard />
          <SchemaMismatchBanner />
          <ConnectionBanner />
          <ExecutionUnknownBanner />
          <GlobalOperationalStateBanner />
          <main className="min-w-0 flex-1 pb-16 md:pb-0">
            <Outlet />
          </main>
        </div>
        <MobileBottomNav />
        <DemoWatermark />
        <Toaster position="top-right" richColors closeButton />
      </div>
    </QueryClientProvider>
  );
}
