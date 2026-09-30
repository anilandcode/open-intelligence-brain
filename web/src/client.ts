import { createContext, useContext } from "react";
import { api } from "./api";

export type BrainClient = typeof api;
export const BrainClientContext = createContext<BrainClient>(api);
export const useBrainClient = () => useContext(BrainClientContext);
