import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { X } from "lucide-react";
import { useSnapshot } from "@/lib/adapters/runtime";
import { Panel } from "@/components/cockpit/panel";
import { StatusBadge, type StatusTone } from "@/components/cockpit/status-badge";
import { EmptyState } from "@/components/cockpit/states";
import { CommandButton } from "@/components/commands/CommandButton";
import {
  BrokerEnvironmentSummary,
  FixtureSourceNotice,
} from "@/components/runtime/environment-badges";
import { fmtNum, fmtPrice, relativeTime } from "@/lib/format";
import type { Order, OrderStatus } from "@/lib/types";

const ACTIVE_STATUSES: OrderStatus[] = ["SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED"];
const isCancellable = (o: Order) => ACTIVE_STATUSES.includes(o.status);

export const Route = createFileRoute("/orders")({
  head: () => ({
    meta: [
      { title: "Orders · XDIRGA METASCAN" },
      { name: "description", content: "Order blotter and lifecycle inspector." },
    ],
  }),
  component: OrdersPage,
});

const statusTone = (s: OrderStatus): StatusTone => {
  if (s === "FILLED" || s === "RECONCILED") return "ok";
  if (s === "REJECTED" || s === "EXECUTION_UNKNOWN" || s === "TIMED_OUT") return "crit";
  if (s === "ACKNOWLEDGED" || s === "PARTIALLY_FILLED" || s === "SUBMITTED") return "info";
  if (s === "CANCELLED") return "neutral";
  return "info";
};

const TABS: Array<{ key: string; label: string; match: (o: Order) => boolean }> = [
  { key: "all", label: "All", match: () => true },
  {
    key: "active",
    label: "Active",
    match: (o) => ["SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED"].includes(o.status),
  },
  {
    key: "pending",
    label: "Pending",
    match: (o) => o.type !== "MARKET" && o.status === "ACKNOWLEDGED",
  },
  { key: "filled", label: "Filled", match: (o) => o.status === "FILLED" },
  { key: "cancelled", label: "Cancelled", match: (o) => o.status === "CANCELLED" },
  { key: "rejected", label: "Rejected", match: (o) => o.status === "REJECTED" },
  {
    key: "unknown",
    label: "Unknown",
    match: (o) => o.status === "EXECUTION_UNKNOWN" || o.status === "TIMED_OUT",
  },
];

function OrdersPage() {
  const snap = useSnapshot();
  const [tab, setTab] = useState("all");
  const [selected, setSelected] = useState<Order | null>(null);

  const activeTab = TABS.find((t) => t.key === tab)!;
  const orders = snap.orders.filter(activeTab.match);

  return (
    <>
      <div className="mx-auto max-w-[1600px] space-y-3 p-3 md:p-4">
        <BrokerEnvironmentSummary />
        <FixtureSourceNotice entity="order" />
        <Panel
          title="Order Blotter"
          subtitle={`${orders.length} of ${snap.orders.length}`}
          toolbar={
            <CommandButton
              kind="order.cancelAll"
              label="Cancel all"
              variant="danger"
              title="Cancel all working orders"
              description="Cancels every SUBMITTED / ACKNOWLEDGED / PARTIALLY_FILLED order at the broker."
              impactSummary={
                <ul className="space-y-0.5">
                  <li>
                    Working orders:{" "}
                    <span className="num">{snap.orders.filter(isCancellable).length}</span>
                  </li>
                  <li>Filled portions are not reversed.</li>
                </ul>
              }
            />
          }
          bodyClassName="p-0"
        >
          <div className="flex flex-wrap items-center gap-1 border-b border-panel-border px-2 py-1.5">
            {TABS.map((t) => {
              const count = snap.orders.filter(t.match).length;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`inline-flex items-center gap-1 rounded-sm px-2 py-1 text-[11px] ${
                    tab === t.key
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/40"
                  }`}
                >
                  {t.label}
                  <span className="num text-[10px] text-muted-foreground">{count}</span>
                </button>
              );
            })}
          </div>
          <div className="overflow-x-auto">
            {orders.length === 0 ? (
              <EmptyState
                title="No orders in this view"
                description="Try another tab or adjust filters."
              />
            ) : (
              <table className="w-full text-[11.5px]">
                <thead className="border-b border-panel-border bg-panel-elevated text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1.5 text-left">Order ID</th>
                    <th className="px-2 py-1.5 text-left">Ticket</th>
                    <th className="px-2 py-1.5 text-left">Symbol</th>
                    <th className="px-2 py-1.5 text-left">Side</th>
                    <th className="px-2 py-1.5 text-left">Type</th>
                    <th className="px-2 py-1.5 text-right">Vol</th>
                    <th className="px-2 py-1.5 text-right">Req</th>
                    <th className="px-2 py-1.5 text-right">Filled</th>
                    <th className="px-2 py-1.5 text-right">SL/TP</th>
                    <th className="px-2 py-1.5 text-left">Strategy</th>
                    <th className="px-2 py-1.5 text-left">Status</th>
                    <th className="px-2 py-1.5 text-left">Updated</th>
                    <th className="px-2 py-1.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr
                      key={o.id}
                      onClick={() => setSelected(o)}
                      className="cursor-pointer border-b border-panel-border/60 hover:bg-muted/40"
                    >
                      <td className="num px-2 py-1.5">{o.id}</td>
                      <td className="num px-2 py-1.5 text-muted-foreground">
                        {o.brokerTicket ?? "—"}
                      </td>
                      <td className="num px-2 py-1.5 font-semibold">{o.symbol}</td>
                      <td className="px-2 py-1.5">
                        <StatusBadge tone={o.side === "BUY" ? "ok" : "crit"} size="sm">
                          {o.side}
                        </StatusBadge>
                      </td>
                      <td className="num px-2 py-1.5">{o.type}</td>
                      <td className="num px-2 py-1.5 text-right">{fmtNum(o.volume, 2)}</td>
                      <td className="num px-2 py-1.5 text-right">{fmtPrice(o.requestedPrice)}</td>
                      <td className="num px-2 py-1.5 text-right">{fmtPrice(o.filledPrice)}</td>
                      <td className="num px-2 py-1.5 text-right text-muted-foreground">
                        {fmtPrice(o.stopLoss)}/{fmtPrice(o.takeProfit)}
                      </td>
                      <td className="px-2 py-1.5 text-muted-foreground">{o.strategy}</td>
                      <td className="px-2 py-1.5">
                        <StatusBadge tone={statusTone(o.status)} size="sm">
                          {o.status.replace("_", " ")}
                        </StatusBadge>
                      </td>
                      <td className="num px-2 py-1.5 text-muted-foreground">
                        {relativeTime(o.updatedAt)}
                      </td>
                      <td className="px-2 py-1.5 text-right" onClick={(e) => e.stopPropagation()}>
                        {isCancellable(o) && (
                          <CommandButton
                            kind="order.cancel"
                            targetId={o.id}
                            label="Cancel"
                            variant="outline"
                            title={`Cancel order ${o.id}`}
                            description={`Cancel ${o.side} ${o.type} ${fmtNum(o.volume, 2)} ${o.symbol}.`}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Panel>
      </div>

      {selected && <OrderDrawer order={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

function OrderDrawer({ order, onClose }: { order: Order; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal>
      <div className="flex-1 bg-background/50 backdrop-blur-sm" onClick={onClose} />
      <div className="flex w-full max-w-lg flex-col overflow-y-auto border-l border-panel-border bg-panel">
        <div className="flex items-start justify-between border-b border-panel-border p-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Order</div>
            <div className="num text-sm font-semibold">{order.id}</div>
            <div className="num text-[11px] text-muted-foreground">corr {order.correlationId}</div>
          </div>
          <div className="flex items-center gap-2">
            {isCancellable(order) && (
              <CommandButton
                kind="order.cancel"
                targetId={order.id}
                label="Cancel order"
                variant="outline"
                title={`Cancel order ${order.id}`}
                description={`Cancel ${order.side} ${order.type} ${fmtNum(order.volume, 2)} ${order.symbol}.`}
              />
            )}
            <button
              onClick={onClose}
              className="rounded-sm border border-panel-border p-1 hover:bg-muted"
              aria-label="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {order.status === "EXECUTION_UNKNOWN" && (
          <div className="border-b border-status-crit/40 bg-status-crit/10 p-3 text-[11.5px] text-status-crit">
            <div className="font-semibold uppercase tracking-wider">EXECUTION_UNKNOWN</div>
            <p className="mt-1">
              This order timed out awaiting broker acknowledgement. Actual broker state is
              uncertain.
              <strong> Do not retry.</strong> Run reconciliation from the Runtime page to resolve.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-y-1 p-4 text-[11.5px]">
          {(
            [
              ["Symbol", order.symbol],
              ["Side", order.side],
              ["Type", order.type],
              ["Volume", fmtNum(order.volume, 2)],
              ["Requested", fmtPrice(order.requestedPrice)],
              ["Filled", fmtPrice(order.filledPrice)],
              ["Stop Loss", fmtPrice(order.stopLoss)],
              ["Take Profit", fmtPrice(order.takeProfit)],
              ["Slippage", order.slippage != null ? `${order.slippage}` : "—"],
              ["Strategy", order.strategy],
              ["Client Req ID", order.clientRequestId],
              ["Broker Ticket", order.brokerTicket ?? "—"],
            ] as Array<[string, string]>
          ).map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-panel-border/50 py-1">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="num truncate pl-2 text-right">{v}</dd>
            </div>
          ))}
        </div>

        <div className="border-t border-panel-border p-4">
          <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
            Lifecycle
          </div>
          <ol className="space-y-1.5">
            {order.lifecycle.map((e, i) => (
              <li
                key={i}
                className="grid grid-cols-[auto_1fr_auto] items-baseline gap-2 text-[11px]"
              >
                <StatusBadge tone={e.step === "REJECTED" ? "crit" : "info"} size="sm">
                  {String(e.step).replace("_", " ")}
                </StatusBadge>
                <span className="truncate">{e.detail}</span>
                <span className="num text-muted-foreground">
                  {relativeTime(e.at)}
                  {e.latencyMs != null && <span> · {e.latencyMs}ms</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>

        {order.rejectionReason && (
          <div className="border-t border-panel-border bg-status-crit/5 p-4 text-[11.5px]">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-status-crit">
              Rejection reason
            </div>
            <p>{order.rejectionReason}</p>
          </div>
        )}
      </div>
    </div>
  );
}
