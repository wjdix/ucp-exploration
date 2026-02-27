import { streamText, stepCountIs, convertToModelMessages } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';
import { createMCPClient } from '@ai-sdk/mcp';
import {
  getPaymentToken,
  generateCheckoutMandateTool,
  createIntentMandateToolWithMessages,
  bindAndCompleteWithIntentTool,
} from '@/lib/tools';

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

  // Extract plain text conversation for intent mandate embedding
  const plainMessages = messages.map((m: { role: string; content: string }) => ({
    role: m.role,
    content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
  }));

  const result = streamText({
    model: anthropic('claude-sonnet-4-20250514'),
    system: `You are a helpful shopping assistant for Demo Electronics Store. You help users browse products and complete purchases using the Universal Commerce Protocol (UCP).

Your tools are auto-discovered from the merchant's UCP MCP server, plus platform tools for payment and authorization.

## Interactive Purchase Flow (user is present)
1. Browse products when asked (use browse_products)
2. Create a checkout when the user picks items (use create_checkout)
3. Collect their name, email, and shipping address (use update_checkout)
4. Confirm the order total with the user
5. Get a payment token (use getPaymentToken)
6. Generate an AP2 checkout mandate (use generateCheckoutMandate) — this cryptographically proves the user approved this purchase
7. Complete the purchase (use complete_checkout) passing the payment token AND the checkout_mandate

IMPORTANT: You MUST generate a checkout mandate before completing checkout. The merchant will reject the payment without it. Pass the checkout_mandate string from generateCheckoutMandate directly to complete_checkout.

## Autonomous Purchase Flow (intent mandates)
When a user wants to set up automatic/autonomous purchasing:
1. Discuss the parameters: what to buy, spending limits, how many times, for how long
2. Create an intent mandate (use createIntentMandate) with the agreed parameters
3. Tell the user the mandate is active and what it authorizes

When completing an autonomous purchase under an intent mandate:
1. Browse/select products and create a checkout as normal
2. Get a payment token
3. Bind the intent mandate (use bindAndCompleteWithIntent) to get the intent_mandate string
4. Complete the purchase (use complete_checkout) passing the payment token AND the intent_mandate

Be concise and friendly.`,
    messages: await convertToModelMessages(messages),
    tools: {
      // MCP-discovered tools from the Business service
      ...businessTools,
      // Direct tool for the Credential Provider (separate UCP participant)
      getPaymentToken,
      // AP2 mandate generation (platform tools)
      generateCheckoutMandate: generateCheckoutMandateTool,
      // Intent mandate tools
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
