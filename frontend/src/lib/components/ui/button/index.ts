import { type VariantProps, tv } from "tailwind-variants";
import type { Button as ButtonPrimitive } from "bits-ui";
import Root from "./button.svelte";

const buttonVariants = tv({
	base: "inline-flex items-center justify-center whitespace-nowrap rounded-md text-[13px] font-bold uppercase tracking-wider ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-40 active:translate-y-[1px] border select-none relative overflow-hidden",
	variants: {
		variant: {
			default: "bg-gradient-to-b from-[#4aa3df] to-[var(--color-action-color)] text-white border-[#2980b9] shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_2px_4px_rgba(0,0,0,0.2)] hover:brightness-110 hover:shadow-[0_0_15px_rgba(52,152,219,0.3)]",
			destructive: "bg-gradient-to-b from-[#ef5350] to-[var(--color-error-color)] text-white border-[#c62828] shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_2px_4px_rgba(0,0,0,0.2)] hover:brightness-110",
			outline: "border-border bg-transparent hover:bg-white/5 hover:text-white",
			secondary: "bg-gradient-to-b from-[#21262d] to-[#161b22] text-[var(--color-text-primary)] border-[var(--color-border-color)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05),0_2px_4px_rgba(0,0,0,0.1)] hover:from-[#2d333b] hover:to-[#21262d] hover:border-[var(--color-text-secondary)]",
			ghost: "border-transparent text-[var(--color-text-secondary)] hover:bg-white/5 hover:text-white",
			link: "border-transparent text-primary underline-offset-4 hover:underline",
            warning: "bg-gradient-to-b from-[#f39c12] to-[#e67e22] text-white border-[#d35400] shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_2px_4px_rgba(0,0,0,0.2)] hover:brightness-110 hover:shadow-[0_0_15px_rgba(230,126,34,0.3)]"
		},
		size: {
			default: "h-9 px-5 py-2",
			sm: "h-8 rounded-md px-3 text-[11px]",
			lg: "h-11 rounded-md px-10 text-[14px]",
			icon: "h-9 w-9 p-0"
		}
	},
	defaultVariants: {
		variant: "default",
		size: "default"
	}
});

type Variant = VariantProps<typeof buttonVariants>["variant"];
type Size = VariantProps<typeof buttonVariants>["size"];

type Props = ButtonPrimitive.Props & {
	variant?: Variant;
	size?: Size;
};

export {
	Root,
	type Props,
	//
	Root as Button,
	buttonVariants
};
