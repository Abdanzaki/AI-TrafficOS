"use client";

import React from "react";
import { AssistantChat } from "@/components/assistant/AssistantChat";

export default function AssistantPage() {
  return (
    <div className="h-[calc(100vh-4rem)] p-3 sm:p-6 flex flex-col">
      <AssistantChat className="flex-1 min-h-0" />
    </div>
  );
}
