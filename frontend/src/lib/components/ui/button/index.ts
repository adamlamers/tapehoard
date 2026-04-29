import { type VariantProps, tv } from "tailwind-variants";
import type { Button as ButtonPrimitive } from "bits-ui";
import Root from "./button.svelte";

const buttonVariants = tv({
	base: "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-40 active:translate-y-[1px] border select-none relative overflow-hidden [&_svg]:shrink-0",
	variants: {
		variant: {
			default: "bg-blue-600 text-white border-blue-700 shadow-lg shadow-blue-500/10 hover:bg-blue-700",
			destructive: "bg-error-color text-white border-red-900 shadow-lg shadow-error-color/10 hover:brightness-110",
			outline: "border-border-color bg-transparent hover:bg-white/5 hover:border-white/20 text-text-primary",
			secondary: "bg-bg-tertiary text-text-primary border-border-color hover:bg-white/5 shadow-sm",
			ghost: "border-transparent text-text-secondary hover:bg-white/5 hover:text-text-primary",
			link: "border-transparent text-blue-500 underline-offset-4 hover:underline",
            warning: "bg-orange-600 text-white border-orange-700 shadow-lg shadow-orange-500/10 hover:brightness-110"
		},
		size: {
			default: "h-9 px-4 py-2",
			sm: "h-8 rounded-md px-3 text-[12px]",
			lg: "h-11 rounded-lg px-8 text-base",
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

type Props = any & {
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
