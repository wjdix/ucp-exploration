import { streamText, stepCountIs } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';
import { createMCPClient } from '@ai-sdk/mcp';
import { getPaymentToken } from '@/lib/tools';

const BUSINESS_MCP_URL = process.env.BUSINESS_MCP_URL || 'http://localhost:8001/mcp/';

export async function POST(req: Request) {
  const { messages } = await req.json();

  // Auto-discover UCP checkout tools from the Business service's MCP server
  const mcpClient = await createMCPClient({
    transport: {
      type: 'http',
      url: BUSINESS_MCP_URL,
    },
  });

  const businessTools = await mcpClient.tools();

  const result = streamText({
    model: anthropic('claude-sonnet-4-20250514'),
    system: `You are a helpful shopping assistant for Demo Electronics Store. You help users browse products and complete purchases using the Universal Commerce Protocol (UCP).

Your tools are auto-discovered from the merchant's UCP MCP server, plus a payment token tool from the Credential Provider.

Guide users through this flow:
1. Browse products when asked (use browse_products)
2. Create a checkout when the user picks items (use create_checkout)
3. Collect their name, email, and shipping address (use update_checkout)
4. Get a payment token (use getPaymentToken) and complete the purchase (use complete_checkout)

Always confirm the order total with the user before completing payment. Be concise and friendly.`,
    messages,
    tools: {
      // MCP-discovered tools from the Business service
      ...businessTools,
      // Direct tool for the Credential Provider (separate UCP participant)
      getPaymentToken,
    },
    stopWhen: stepCountIs(8),
    onFinish: async () => {
      await mcpClient.close();
    },
  });

  return result.toUIMessageStreamResponse();
}
