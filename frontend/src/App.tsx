import "./index.css";
import { FileUploader } from "@/components/file-uploader";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  return (
    <main className="flex min-h-screen w-full items-center justify-center p-6">
      <FileUploader />
      <Toaster position="bottom-right" richColors />
    </main>
  );
}

export default App;
