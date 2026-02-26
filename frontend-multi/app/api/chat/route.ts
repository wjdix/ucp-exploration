import { streamText, stepCountIs, convertToModelMessages } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';
import { createMCPClient } from '@ai-sdk/mcp';
import { getPaymentToken } from '@/lib/tools';

const AGGREGATOR_MCP_URL = process.env.AGGREGATOR_MCP_URL || 'http://localhost:8005/mcp/';

export async function POST(req: Request) {
  const { messages } = await req.json();

  const mcpClient = await createMCPClient({
    transport: {
      type: 'http',
      url: AGGREGATOR_MCP_URL,
    },
  });

  const aggregatorTools = await mcpClient.tools();

  const result = streamText({
    model: anthropic('claude-sonnet-4-20250514'),
    system: `You are a helpful multi-store shopping assistant. You help users search and buy products across multiple stores using the Universal Commerce Protocol (UCP).

Your tools are auto-discovered from the store aggregator's MCP server, plus a payment token tool from the Credential Provider.

Guide users through this flow:
1. Search products across all stores (use search_products with an optional query)
2. Create a checkout when the user picks items - specify the store_id from the product listing (use create_checkout)
3. Collect their name, email, and shipping address (use update_checkout)
4. Get a payment token (use getPaymentToken with the store name as merchantName) and complete the purchase (use complete_checkout)

Products come from different stores. Each product listing includes store_id and store_name so you know which store it belongs to.
When creating a checkout, all items must be from the same store. If the user wants items from multiple stores, create separate checkouts for each store.
Always confirm the order total with the user before completing payment. Be concise and friendly.`,
    messages: await convertToModelMessages(messages),
    tools: {
      ...aggregatorTools,
      getPaymentToken,
    },
    stopWhen: stepCountIs(8),
    onFinish: async () => {
      await mcpClient.close();
    },
  });

  return result.toUIMessageStreamResponse();
}
