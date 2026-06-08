import React from 'react';
import { Breadcrumb, BreadcrumbItem } from 'flowbite-react';
import { HiHome, HiViewBoards } from 'react-icons/hi';
import GraphIcon from './icons/GraphIcon';
import { extractGraphName } from '../utils/QuadUtils';

interface NavigationBreadcrumbProps {
  spaceId?: string;
  graphId?: string;
  spaceName?: string;
  graphName?: string;
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
  spaceName,
  graphName,
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

  const displaySpaceName = spaceName || spaceId;
  const displayGraphName = graphName || extractGraphName(graphId);

  return (
    <Breadcrumb className={className}>
      <BreadcrumbItem href="/" icon={HiHome}>
        Home
      </BreadcrumbItem>
      <BreadcrumbItem href="/spaces" icon={HiViewBoards}>
        Spaces
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}`}>
        {displaySpaceName}
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}/graphs`} icon={GraphIcon}>
        Graphs
      </BreadcrumbItem>
      <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
        {displayGraphName}
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
