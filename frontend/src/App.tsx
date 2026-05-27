import { QuizEditor } from "./features/quiz-editor/QuizEditor";
import { QuizHome } from "./features/play/QuizHome";

export default function App() {
  return window.location.pathname === "/author" ? <QuizEditor /> : <QuizHome />;
}
