import { streamText, stepCountIs, convertToModelMessages } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';
import { createMCPClient } from '@ai-sdk/mcp';
import {
  getPaymentToken,
  generateCheckoutMandateTool,
  createIntentMandateToolWithMessages,
  bindAndCompleteWithIntentTool,
} from '@/lib/tools';

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

  const plainMessages = messages.map((m: { role: string; content: string }) => ({
    role: m.role,
    content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
  }));

  const result = streamText({
    model: anthropic('claude-sonnet-4-20250514'),
    system: `You are a helpful multi-store shopping assistant. You help users search and buy products across multiple stores using the Universal Commerce Protocol (UCP).

Your tools are auto-discovered from the store aggregator's MCP server, plus platform tools for payment and authorization.

## Interactive Purchase Flow
1. Search products across all stores (use search_products with an optional query)
2. Create a checkout when the user picks items - specify the store_id from the product listing (use create_checkout)
3. Collect their name, email, and shipping address (use update_checkout)
4. Confirm the order total with the user
5. Get a payment token (use getPaymentToken with the store name as merchantName)
6. Generate an AP2 checkout mandate (use generateCheckoutMandate with the store_id and session_id)
7. Complete the purchase (use complete_checkout) passing the payment token AND the checkout_mandate

IMPORTANT: You MUST generate a checkout mandate before completing checkout. The merchant will reject the payment without it.

Products come from different stores. Each product listing includes store_id and store_name.
When creating a checkout, all items must be from the same store. Create separate checkouts for items from different stores.

## Autonomous Purchase Flow (intent mandates)
When a user wants to set up automatic/autonomous purchasing:
1. Discuss parameters: what to buy, spending limits, which stores, how many times, for how long
2. Create an intent mandate (use createIntentMandate) with the agreed parameters
3. Tell the user the mandate is active

When completing an autonomous purchase under an intent mandate:
1. Create checkout as normal
2. Get a payment token
3. Bind the intent mandate (use bindAndCompleteWithIntent)
4. Complete the purchase with the intent_mandate

Be concise and friendly.`,
    messages: await convertToModelMessages(messages),
    tools: {
      ...aggregatorTools,
      getPaymentToken,
      generateCheckoutMandate: generateCheckoutMandateTool,
      createIntentMandate: createIntentMandateToolWithMessages(plainMessages),
      bindAndCompleteWithIntent: bindAndCompleteWithIntentTool,
    },
    stopWhen: stepCountIs(10),
    onFinish: async () => {
      await mcpClient.close();
    },
  });

  return result.toUIMessageStreamResponse();
}
