/// <reference types="vite/client" />

interface Window {
  flowerDesktop?: {
    chooseDirectory: () => Promise<string | null>;
    platform: string;
  };
}
