import { useAppDispatch, useAppSelector } from '../store';
import { themeToggled } from '../store/uiSlice';

/** Header action that flips dark/light. uiSync persists the choice and stamps <html>. */
export function ThemeToggle() {
  const dispatch = useAppDispatch();
  const theme = useAppSelector((state) => state.ui.theme);
  const target = theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      className="ghost-button"
      aria-label={`Switch to ${target} theme`}
      onClick={() => dispatch(themeToggled())}
    >
      {target === 'light' ? 'Light theme' : 'Dark theme'}
    </button>
  );
}
