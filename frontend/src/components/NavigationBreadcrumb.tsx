import React from 'react';
import { Breadcrumb, BreadcrumbItem } from 'flowbite-react';
import { HiHome, HiViewBoards } from 'react-icons/hi';
import { mockSpaces, mockGraphs } from '../mock';
import GraphIcon from './icons/GraphIcon';

interface NavigationBreadcrumbProps {
  spaceId?: string;
  graphId?: string;
  currentPageName: string;
  currentPageIcon: React.FC<React.SVGProps<SVGSVGElement>>;
  className?: string;
  parentPageName?: string;
  parentPagePath?: string;
  parentPageIcon?: React.FC<React.SVGProps<SVGSVGElement>>;
}

const NavigationBreadcrumb: React.FC<NavigationBreadcrumbProps> = ({
  spaceId,
  graphId,
  currentPageName,
  currentPageIcon: CurrentPageIcon,
  className = "mb-6",
  parentPageName,
  parentPagePath,
  parentPageIcon: ParentPageIcon
}) => {
  // Only show breadcrumbs when on hierarchical URLs
  if (!(spaceId && graphId)) {
    return null;
  }

  // Look up the space and graph data using IDs
  const space = mockSpaces.find(s => s.space === spaceId);
  const graphIdNum = parseInt(graphId);
  const graph = mockGraphs.find(g => g.id === graphIdNum && g.space_id === spaceId);

  // Don't show if data not found
  if (!space || !graph) {
    return null;
  }

  return (
    <Breadcrumb className={className}>
      <BreadcrumbItem href="/" icon={HiHome}>
        Home
      </BreadcrumbItem>
      <BreadcrumbItem href="/spaces" icon={HiViewBoards}>
        Spaces
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}`}>
        {space.space_name}
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}/graphs`} icon={GraphIcon}>
        Graphs
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
        {graph.graph_name}
      </BreadcrumbItem>
      {parentPageName && parentPagePath && ParentPageIcon ? (
        <>
          <BreadcrumbItem href={parentPagePath} icon={ParentPageIcon}>
            {parentPageName}
          </BreadcrumbItem>
          <BreadcrumbItem>
            {currentPageName}
          </BreadcrumbItem>
        </>
      ) : (
        <BreadcrumbItem icon={CurrentPageIcon}>
          {currentPageName}
        </BreadcrumbItem>
      )}
    </Breadcrumb>
  );
};

export default NavigationBreadcrumb;
