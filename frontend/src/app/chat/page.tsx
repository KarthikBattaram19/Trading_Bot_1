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
      <div className="flex h-[calc(100vh-4rem)] flex-col p-6">
        <div className="mb-4">
          <h1 className="text-xl font-semibold text-white">AI assistant</h1>
          <p className="mt-1 text-sm text-gray-500">
            RAG-powered Q&A over strategy books, decision packets, and failure memory
          </p>
        </div>
        <ChatView decisionId={decision} />
      </div>
    </>
  );
}
