import { Channel, ConnectorInstallT, McpClientT } from "@/lib/api";

export type MainTab = "my" | "explore" | "custom";
export type DetailTab = "overview" | "tools" | "config" | "diagnostics";

export interface UnifiedIntegrationItem {
  id: string;
  slug: string;
  name: string;
  summary: string;
  icon: string;
  kind: "connector_rest" | "connector_mcp" | "raw_mcp" | "channel_email" | "channel_telegram";
  status: "connected" | "needs_auth" | "needs_setup" | "degraded" | "error" | "installed";
  status_detail?: string | null;
  account?: string | null;
  total_tools: number;
  enabled_tools: number;
  last_verified?: string | null;
  auth_kind?: string;
  source: "catalog" | "custom" | "mcp" | "channel";
  raw_connector?: ConnectorInstallT;
  raw_mcp?: McpClientT;
  raw_channel?: Channel;
}

