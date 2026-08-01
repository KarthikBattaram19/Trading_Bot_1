import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { ChatView } from "@/components/chat/chat-view";

interface PageProps {
  searchParams: Promise<{ decision?: string }>;
}

export default async function ChatPage({ searchParams }: PageProps) {
  const status = await getBotStatus();
  const { decision } = await searchParams;

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex h-[calc(100vh-var(--topbar,64px))] flex-1 flex-col p-margin-page">
        <div className="mb-4">
          <h1 className="text-headline-lg text-on-surface">AI Assistant</h1>
          <p className="mt-1 text-body-md text-on-surface-variant">
            RAG-powered Q&amp;A over Volatility Trading (Track B1), with citations
            from the knowledge base.
          </p>
        </div>
        <ChatView decisionId={decision} />
      </main>
    </>
  );
}
